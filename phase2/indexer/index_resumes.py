"""
Phase 2 Resume Indexer — core logic.

Reads Phase 1 extracted JSON files from S3, chunks each resume into
section-aware pieces, generates Voyage AI embeddings, and stores the
resulting documents in MongoDB Atlas.

Entry point:  python -m phase2.index_resumes  [options]

Pipeline per resume
-------------------
1. List   s3://BUCKET/extracted/*.json
2. Parse  Phase 1 JSON  (status, text, blocks, source.key)
3. Derive candidate_id  from source.key  (PDF filename without extension)
4. Hash   content_hash  = SHA-256(text)
5. Skip   if existing hash in MongoDB matches  (idempotent)
6. Delete stale chunks  if hash changed
7. Chunk  text into section-aware TextChunk list
8. Embed  chunks via Voyage AI  (input_type="document", batched)
9. Store  CandidateChunk documents in MongoDB  (upsert by chunk_id)

Idempotency
-----------
Re-running the indexer on an unchanged resume is a no-op.
If the resume text changes (re-extracted by Phase 1), all old chunks for
that candidate_id are deleted and fresh chunks are inserted.

Security
--------
- AWS credentials come from the environment / ~/.aws/credentials.
- VOYAGE_API_KEY and MONGODB_URI come from environment variables.
- Resume text is NEVER logged (only candidate_id, counts, sections).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError
from pymongo import MongoClient
from pymongo.collection import Collection

from phase2 import config
from phase2.indexer.chunker import TextChunk, chunk_resume, compute_content_hash
from phase2.indexer.embedder import embed_texts
from phase2.models.schemas import CandidateChunk

logger = logging.getLogger(__name__)


# ─── Candidate ID derivation ───────────────────────────────────────────────────

def derive_candidate_id(source_key: str) -> str:
    """
    Derive a human-readable candidate_id from the Phase 1 source S3 key.

    Phase 1 stores the original upload path in ``data["source"]["key"]``, e.g.:
        "incoming/john-doe.pdf"  →  candidate_id = "john-doe"

    Transformation rules:
    - Take the basename (last path component).
    - Strip the file extension.
    - Lowercase; replace non-alphanumeric / non-hyphen / non-underscore
      characters with hyphens.
    - Collapse consecutive hyphens; strip leading/trailing hyphens.

    Examples:
        "incoming/john-doe.pdf"           → "john-doe"
        "incoming/Jane Smith Resume.pdf"  → "jane-smith-resume"
        "incoming/C001_alice.pdf"         → "c001_alice"
    """
    filename = source_key.split("/")[-1]
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = re.sub(r"[^a-zA-Z0-9\-_]+", "-", name.lower())
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "unknown"


# ─── S3 helpers ────────────────────────────────────────────────────────────────

def list_extracted_keys(s3_client, bucket: str, prefix: str) -> List[str]:
    """List all ``*.json`` objects under the given S3 prefix."""
    keys: List[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                keys.append(key)
    logger.info("Found %d JSON files in s3://%s/%s", len(keys), bucket, prefix)
    return keys


def read_phase1_json(s3_client, bucket: str, key: str) -> Optional[dict]:
    """Download and parse a Phase 1 extracted JSON from S3."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        if code == "NoSuchKey":
            logger.error("S3 key not found: s3://%s/%s", bucket, key)
        else:
            logger.error(
                "S3 ClientError reading s3://%s/%s: %s (%s)",
                bucket, key, exc, code,
            )
        return None
    except json.JSONDecodeError as exc:
        logger.error("Malformed JSON in s3://%s/%s: %s", bucket, key, exc)
        return None


# ─── MongoDB helpers ───────────────────────────────────────────────────────────

def ensure_operational_indexes(collection: Collection) -> None:
    """
    Create compound indexes needed for fast idempotency checks and lookups.

    NOTE: These are regular MongoDB indexes — NOT Atlas Search or Vector Search
    indexes (those must be created in the Atlas UI; see README).
    """
    collection.create_index(
        [("source_key", 1), ("content_hash", 1)],
        background=True,
        name="idx_source_key_hash",
    )
    collection.create_index(
        [("candidate_id", 1)],
        background=True,
        name="idx_candidate_id",
    )
    logger.debug("Operational indexes ensured.")


def get_existing_hash(collection: Collection, source_key: str) -> Optional[str]:
    """Return the stored content_hash for a source_key, or None if not indexed."""
    doc = collection.find_one(
        {"source_key": source_key},
        {"content_hash": 1, "_id": 0},
    )
    return doc["content_hash"] if doc else None


def delete_candidate_chunks(collection: Collection, candidate_id: str) -> int:
    """Delete all chunks for a candidate. Returns count deleted."""
    result = collection.delete_many({"candidate_id": candidate_id})
    return result.deleted_count


def upsert_chunks(collection: Collection, chunk_docs: List[dict]) -> int:
    """Upsert chunk documents by ``_id`` (= chunk_id). Returns count upserted."""
    count = 0
    for doc in chunk_docs:
        collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        count += 1
    return count


# ─── Core indexing logic ───────────────────────────────────────────────────────

def index_all(
    s3_client,
    collection: Collection,
    bucket: str,
    prefix: str,
    dry_run: bool = False,
    filter_candidate: Optional[str] = None,
    force_reindex: bool = False,
) -> Dict[str, int]:
    """
    Index all Phase 1 extracted resumes found under ``s3://bucket/prefix``.

    Args:
        s3_client:        Boto3 S3 client.
        collection:       MongoDB ``candidate_chunks`` collection.
        bucket:           S3 bucket name.
        prefix:           S3 prefix (e.g. ``"extracted/"``).
        dry_run:          If True, report what would happen but make no writes.
        filter_candidate: If set, only process the specified candidate_id.
        force_reindex:    If True, re-embed even if the content hash is unchanged.

    Returns:
        Stats dict with counts of candidates processed, skipped, etc.
    """
    stats: Dict[str, int] = {
        "candidates_found": 0,
        "candidates_skipped": 0,
        "candidates_indexed": 0,
        "candidates_reindexed": 0,
        "candidates_failed": 0,
        "total_chunks": 0,
    }

    keys = list_extracted_keys(s3_client, bucket, prefix)

    for key in keys:
        # ── Parse Phase 1 JSON ────────────────────────────────────────────────
        data = read_phase1_json(s3_client, bucket, key)
        if data is None:
            stats["candidates_failed"] += 1
            continue

        if data.get("status") != "SUCCEEDED":
            logger.debug("Skipping %s: status=%s", key, data.get("status"))
            continue

        text: str = data.get("text", "").strip()
        if not text:
            logger.warning("Empty text field in %s — skipping.", key)
            stats["candidates_failed"] += 1
            continue

        # ── Derive candidate_id ───────────────────────────────────────────────
        # Use the original PDF path stored in source.key, not the Textract job-id key.
        source_file_key: str = data.get("source", {}).get("key", key)
        candidate_id: str = derive_candidate_id(source_file_key)

        if filter_candidate and candidate_id != filter_candidate:
            continue

        stats["candidates_found"] += 1
        source_key: str = key  # "extracted/<textract-job-id>.json"

        # ── Idempotency check ─────────────────────────────────────────────────
        content_hash: str = compute_content_hash(text)
        existing_hash: Optional[str] = get_existing_hash(collection, source_key)

        if existing_hash == content_hash and not force_reindex:
            logger.info("Candidate %s: unchanged — skipping (hash match).", candidate_id)
            stats["candidates_skipped"] += 1
            continue

        if dry_run:
            action = "re-index" if existing_hash else "index"
            logger.info(
                "[DRY RUN] Would %s candidate: %s  (%s)",
                action, candidate_id, key,
            )
            stats["candidates_indexed"] += 1
            continue

        # ── Delete stale chunks if resume changed ─────────────────────────────
        reindexing = False
        if existing_hash and existing_hash != content_hash:
            deleted = delete_candidate_chunks(collection, candidate_id)
            logger.info(
                "Candidate %s: resume changed — deleted %d stale chunk(s).",
                candidate_id, deleted,
            )
            reindexing = True

        # ── Chunk ─────────────────────────────────────────────────────────────
        blocks: list = data.get("blocks", [])
        chunks: List[TextChunk] = chunk_resume(candidate_id, source_key, text, blocks)

        if not chunks:
            logger.warning(
                "No chunks generated for candidate %s — skipping.", candidate_id
            )
            stats["candidates_failed"] += 1
            continue

        detected_sections = list(dict.fromkeys(c.section for c in chunks))
        logger.info(
            "Candidate %s: %d chunk(s) | sections: %s",
            candidate_id, len(chunks), detected_sections,
        )

        # ── Embed ─────────────────────────────────────────────────────────────
        try:
            embeddings = embed_texts(
                [c.text for c in chunks],
                input_type="document",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Embedding failed for candidate %s: %s", candidate_id, exc
            )
            stats["candidates_failed"] += 1
            continue

        if len(embeddings) != len(chunks):
            logger.error(
                "Embedding count mismatch for candidate %s: expected %d, got %d.",
                candidate_id, len(chunks), len(embeddings),
            )
            stats["candidates_failed"] += 1
            continue

        # ── Build MongoDB documents ───────────────────────────────────────────
        chunk_docs: List[dict] = []
        for chunk, embedding in zip(chunks, embeddings):
            doc = CandidateChunk(
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
                    "source_s3_bucket": bucket,
                },
            ).to_mongo_doc()
            chunk_docs.append(doc)

        # ── Store ─────────────────────────────────────────────────────────────
        try:
            inserted = upsert_chunks(collection, chunk_docs)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MongoDB insert failed for candidate %s: %s", candidate_id, exc
            )
            stats["candidates_failed"] += 1
            continue

        stats["total_chunks"] += inserted
        if reindexing:
            stats["candidates_reindexed"] += 1
            logger.info(
                "Candidate %s: re-indexed %d chunk(s).", candidate_id, inserted
            )
        else:
            stats["candidates_indexed"] += 1
            logger.info(
                "Candidate %s: indexed %d chunk(s).", candidate_id, inserted
            )

    return stats


# ─── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phase2.index_resumes",
        description=(
            "Phase 2 indexer: read Phase 1 S3 extractions → chunk → embed "
            "(Voyage AI) → store in MongoDB Atlas."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be indexed without making any writes.",
    )
    parser.add_argument(
        "--candidate",
        metavar="CANDIDATE_ID",
        help="Process only the specified candidate (derived from PDF filename).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index even if the resume's content hash is unchanged.",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        metavar="BUCKET_NAME",
        help="Override S3 bucket (defaults to S3_BUCKET_NAME env var).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Validate required environment variables
    try:
        config.validate()
    except EnvironmentError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    bucket = args.bucket or config.S3_BUCKET_NAME
    prefix = config.S3_EXTRACTED_PREFIX

    logger.info("=== Phase 2 Indexer ===")
    logger.info("Source:  s3://%s/%s", bucket, prefix)
    logger.info(
        "Target:  MongoDB %s.%s",
        config.MONGODB_DATABASE, config.MONGODB_COLLECTION,
    )
    logger.info(
        "Model:   %s (%d dims)",
        config.VOYAGE_MODEL, config.VOYAGE_EMBEDDING_DIMENSIONS,
    )
    if args.dry_run:
        logger.info("Mode:    DRY RUN — no writes will occur")

    # Connect MongoDB
    try:
        mongo_client = MongoClient(
            config.MONGODB_URI, serverSelectionTimeoutMS=15_000
        )
        mongo_client.admin.command("ping")
        collection = mongo_client[config.MONGODB_DATABASE][config.MONGODB_COLLECTION]
        logger.info("Connected to MongoDB Atlas.")
    except Exception as exc:  # noqa: BLE001
        logger.error("MongoDB connection failed: %s", exc)
        sys.exit(1)

    # Ensure operational indexes exist
    try:
        ensure_operational_indexes(collection)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ensure operational indexes: %s", exc)

    # Connect S3
    s3_client = boto3.client("s3", region_name=config.AWS_REGION)

    # Run indexing
    try:
        stats = index_all(
            s3_client=s3_client,
            collection=collection,
            bucket=bucket,
            prefix=prefix,
            dry_run=args.dry_run,
            filter_candidate=args.candidate,
            force_reindex=args.force,
        )
    except KeyboardInterrupt:
        logger.warning("Indexing interrupted by user (KeyboardInterrupt).")
        sys.exit(130)
    finally:
        mongo_client.close()

    # Final report
    sep = "─" * 52
    logger.info(sep)
    logger.info("Indexing complete.")
    logger.info("  Candidates found:      %4d", stats["candidates_found"])
    logger.info("  Newly indexed:         %4d", stats["candidates_indexed"])
    logger.info("  Re-indexed (changed):  %4d", stats["candidates_reindexed"])
    logger.info("  Skipped (unchanged):   %4d", stats["candidates_skipped"])
    logger.info("  Failed:                %4d", stats["candidates_failed"])
    logger.info("  Total chunks stored:   %4d", stats["total_chunks"])
    logger.info(sep)

    if stats["candidates_failed"] > 0:
        sys.exit(1)
