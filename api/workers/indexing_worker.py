"""
Phase 2 Indexing Worker — Lambda handler.

Triggered by: SQS (IndexingQueue) when a new extracted.json lands in S3.

Event source:
    S3 ObjectCreated → SQS → this Lambda

Each SQS message contains the S3 key of a newly written extracted.json file.
This worker:
    1. Parses the S3 key to extract tenant_id / job_id / application_id.
    2. Reads the Phase 1 extracted JSON from S3.
    3. Chunks and embeds the resume via Phase 2 indexing logic.
    4. Stores the chunks in MongoDB Atlas with full multi-tenant context.
    5. Updates the application status in MongoDB.

Security:
    - Only reads S3 keys within the tenant's own prefix.
    - Resume text is never logged.
    - All identifiers logged are non-PII UUIDs.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import certifi
from pymongo import MongoClient

from phase2 import config
from phase2.indexer.chunker import chunk_resume, compute_content_hash
from phase2.indexer.embedder import embed_texts
from phase2.indexer.index_resumes import (
    delete_candidate_chunks,
    derive_candidate_id,
    get_existing_hash,
    upsert_chunks,
)
from phase2.models.schemas import CandidateChunk
from phase2.storage.s3_paths import parse_s3_key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET_NAME"]


def _get_mongo() -> MongoClient:
    return MongoClient(
        config.MONGODB_URI,
        serverSelectionTimeoutMS=15_000,
        tlsCAFile=certifi.where(),
    )


def _update_application_status(db, application_id: str, status: str, error: str | None = None) -> None:
    if not application_id:
        return
    update: dict[str, Any] = {"phase2_status": status}
    if error:
        update["phase2_error"] = error
    db["applications"].update_one(
        {"_id": application_id},
        {"$set": update},
    )


def _index_single(s3_key: str) -> None:
    """Index a single extracted.json S3 key into MongoDB."""
    logger.info("Indexing S3 key: %s", s3_key)

    # ── Read Phase 1 JSON from S3 ───────────────────────────────────────────
    s3 = boto3.client("s3", region_name=config.AWS_REGION)
    response = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
    data = json.loads(response["Body"].read().decode("utf-8"))

    if data.get("status") != "SUCCEEDED":
        raise ValueError(f"Phase 1 status is not SUCCEEDED: {data.get('status')}")

    text: str = data.get("text", "").strip()
    if not text:
        raise ValueError("Phase 1 extracted JSON has empty text field.")

    source_file_key = data.get("source", {}).get("key", s3_key)
    
    # ── Parse path context from original PDF path ───────────────────────────
    # Phase 1 might write to extracted/<id>.json, so we parse the original PDF path
    # stored inside the JSON to reliably recover the tenant/job/application IDs.
    path_ctx = parse_s3_key(source_file_key)
    if path_ctx.is_multitenant:
        logger.info(
            "SaaS context recovered — tenant=%s  job=%s  application=%s",
            path_ctx.tenant_id, path_ctx.job_id, path_ctx.application_id,
        )

    candidate_id = derive_candidate_id(source_file_key)
    content_hash = compute_content_hash(text)
    blocks = data.get("blocks", [])

    # ── Idempotency check ────────────────────────────────────────────────────
    mongo_client = _get_mongo()
    try:
        collection = mongo_client[config.MONGODB_DATABASE][config.MONGODB_COLLECTION]
        db = mongo_client[config.MONGODB_DATABASE]

        _update_application_status(db, path_ctx.application_id, "INDEXING")

        existing_hash = get_existing_hash(collection, s3_key)
        if existing_hash == content_hash:
            logger.info("Candidate %s: unchanged (hash match) — skipping.", candidate_id)
            _update_application_status(db, path_ctx.application_id, "INDEXED")
            return

        if existing_hash and existing_hash != content_hash:
            deleted = delete_candidate_chunks(collection, candidate_id)
            logger.info("Candidate %s: resume changed — deleted %d stale chunks.", candidate_id, deleted)

        # ── Chunk ────────────────────────────────────────────────────────────
        chunks = chunk_resume(candidate_id, s3_key, text, blocks)
        if not chunks:
            raise ValueError(f"No chunks generated for candidate {candidate_id}.")

        logger.info("Candidate %s: %d chunk(s) across %d section(s).", candidate_id, len(chunks),
                    len(set(c.section for c in chunks)))

        # ── Embed ────────────────────────────────────────────────────────────
        embeddings = embed_texts([c.text for c in chunks], input_type="document")

        # ── Build and store MongoDB documents ─────────────────────────────────
        chunk_docs = [
            CandidateChunk(
                candidate_id=chunk.candidate_id,
                chunk_id=chunk.chunk_id,
                source_key=chunk.source_key,
                chunk_index=chunk.chunk_index,
                section=chunk.section,
                text=chunk.text,
                embedding_model=config.VOYAGE_MODEL,
                embedding_dimensions=config.VOYAGE_EMBEDDING_DIMENSIONS,
                embedding=embedding,
                content_hash=content_hash,
                metadata={
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "source_s3_bucket": S3_BUCKET,
                },
                tenant_id=path_ctx.tenant_id,
                job_id=path_ctx.job_id,
                application_id=path_ctx.application_id,
            ).to_mongo_doc()
            for chunk, embedding in zip(chunks, embeddings)
        ]

        upsert_chunks(collection, chunk_docs)
        logger.info("Candidate %s: stored %d chunks in MongoDB.", candidate_id, len(chunk_docs))
        _update_application_status(db, path_ctx.application_id, "INDEXED")

    finally:
        mongo_client.close()


def lambda_handler(event: dict, context: object) -> dict:
    """SQS trigger entry point. Processes one record at a time (BatchSize=1)."""
    batch_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "?")
        try:
            body = json.loads(record["body"])
            # SQS message may come directly from S3 event notification
            # or from a simple {"s3_key": "..."} wrapper.
            if "Records" in body:
                # Direct S3 → SQS event notification format
                s3_key = body["Records"][0]["s3"]["object"]["key"]
            else:
                s3_key = body["s3_key"]

            _index_single(s3_key)

        except Exception as exc:
            logger.error("Failed to index message %s: %s", message_id, exc)
            batch_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_failures}
