"""
Phase 2+3 Screening Worker — Lambda handler.

Triggered by: SQS (ScreeningQueue) when HR clicks "Screen Candidates".

This worker:
    1. Receives a screening_run_id, tenant_id, and job_id from SQS.
    2. Loads the job description text from MongoDB.
    3. Runs Phase 2 hybrid retrieval (BM25 + Vector Search + RRF).
    4. Runs Phase 3 semantic reranking (Voyage rerank-2.5).
    5. Stores results in MongoDB screening_runs collection.
    6. Writes output artifacts to S3.

Phase 2 and Phase 3 logic is fully reused from the existing modules —
only the entry point and result persistence change.

Security:
    - All MongoDB queries are scoped with tenant_id + job_id.
    - Resume text is never logged.
    - All identifiers are non-PII internal IDs.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import boto3
import certifi
from pymongo import MongoClient

from phase2 import config
from phase2.indexer.embedder import embed_texts
from phase2.retrieval.fusion import fuse_results
from phase2.retrieval.lexical_search import lexical_search
from phase2.retrieval.vector_search import vector_search
from phase3 import config as p3config
from phase3.reranker.document_builder import build_candidate_document
from phase3.reranker.voyage_reranker import rerank_documents

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET_NAME"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_mongo() -> MongoClient:
    return MongoClient(
        config.MONGODB_URI,
        serverSelectionTimeoutMS=15_000,
        tlsCAFile=certifi.where(),
    )


def _get_job_description(db, job_id: str, tenant_id: str) -> Optional[str]:
    """Fetch the job description text from MongoDB."""
    job = db["jobs"].find_one(
        {"_id": job_id, "tenant_id": tenant_id},
        {"description": 1}
    )
    return job["description"] if job else None


def _update_run_status(db, run_id: str, status: str, update: dict = None) -> None:
    payload = {"status": status, "updated_at": _now_iso()}
    if update:
        payload.update(update)
    db["screening_runs"].update_one({"_id": run_id}, {"$set": payload})


def _run_screening(screening_run_id: str, tenant_id: str, job_id: str) -> None:
    """Execute Phase 2+3 screening pipeline and persist results."""
    start_time = time.time()
    logger.info(
        "Starting screening run %s (tenant=%s job=%s)",
        screening_run_id, tenant_id, job_id
    )

    mongo_client = _get_mongo()
    try:
        db = mongo_client[config.MONGODB_DATABASE]
        collection = db[config.MONGODB_COLLECTION]

        _update_run_status(db, screening_run_id, "RUNNING_PHASE2",
                           {"phase2_status": "RUNNING"})

        # ── Load Job Description ───────────────────────────────────────────
        jd_text = _get_job_description(db, job_id, tenant_id)
        if not jd_text:
            raise ValueError(f"Job description not found for job_id={job_id}")

        # ── Phase 2: Embed JD ──────────────────────────────────────────────
        logger.info("Embedding job description...")
        jd_embedding = embed_texts([jd_text], input_type="query")[0]

        # ── Phase 2: Hybrid Retrieval ──────────────────────────────────────
        lex_k = config.LEXICAL_TOP_K
        vec_k = config.VECTOR_TOP_K
        final_k = config.FINAL_TOP_K

        logger.info("Running BM25 (top_k=%d)...", lex_k)
        lex_hits = lexical_search(
            collection, jd_text,
            top_k=lex_k, tenant_id=tenant_id, job_id=job_id
        )

        logger.info("Running Vector Search (top_k=%d)...", vec_k)
        vec_hits = vector_search(
            collection, jd_embedding,
            top_k=vec_k, tenant_id=tenant_id, job_id=job_id
        )

        fused = fuse_results(lex_hits, vec_hits, final_top_k=final_k, rrf_k=config.RRF_K)
        logger.info("Phase 2 complete: %d unique candidates.", len(fused))

        _update_run_status(db, screening_run_id, "RUNNING_PHASE3", {
            "phase2_status": "COMPLETED",
            "phase2_candidate_count": len(fused),
            "phase3_status": "RUNNING",
        })

        if not fused:
            _update_run_status(db, screening_run_id, "COMPLETED", {
                "phase3_status": "SKIPPED",
                "reason": "No candidates returned from Phase 2.",
                "completed_at": _now_iso(),
            })
            return

        # ── Phase 3: Reconstruct Candidate Documents ───────────────────────
        logger.info("Reconstructing %d candidate documents for reranking...", len(fused))
        valid_candidates = []
        documents = []

        for prov in fused:
            doc = build_candidate_document(collection, prov.candidate_id)
            if not doc.text.strip():
                logger.warning("No text for candidate %s — skipping.", prov.candidate_id)
                continue
            valid_candidates.append(prov)
            documents.append(doc.text)

        # ── Phase 3: Voyage Rerank ─────────────────────────────────────────
        logger.info("Calling Voyage rerank-2.5 on %d documents...", len(documents))
        rerank_results = rerank_documents(
            query=jd_text,
            documents=documents,
            model=p3config.VOYAGE_RERANK_MODEL,
        )

        # ── Build Final Candidate List ─────────────────────────────────────
        p2_ranks = {prov.candidate_id: i + 1 for i, prov in enumerate(fused)}
        final_candidates = []

        for rank_pos, result in enumerate(rerank_results, start=1):
            prov = valid_candidates[result["index"]]
            p2_rank = p2_ranks[prov.candidate_id]
            final_candidates.append({
                "candidate_id": prov.candidate_id,
                "rerank_rank": rank_pos,
                "rerank_score": round(result["relevance_score"], 6),
                "rank_change": p2_rank - rank_pos,
                "phase2": {
                    "hybrid_score": round(prov.rrf_score, 6),
                    "lexical_rank": prov.lexical_rank,
                    "vector_rank": prov.vector_rank,
                    "matched_chunks": [
                        {"chunk_id": cid, "section": sec}
                        for cid, sec in prov.matched_chunks.items()
                    ],
                },
                "source_key": prov.source_key,
            })

        elapsed = round(time.time() - start_time, 2)
        logger.info("Phase 3 complete: %d candidates reranked in %.1fs.", len(final_candidates), elapsed)

        # ── Persist results in MongoDB ─────────────────────────────────────
        _update_run_status(db, screening_run_id, "COMPLETED", {
            "phase3_status": "COMPLETED",
            "candidates": final_candidates,
            "candidate_count": len(final_candidates),
            "processing_time_sec": elapsed,
            "completed_at": _now_iso(),
        })

        # ── Write artifacts to S3 ──────────────────────────────────────────
        artifact_key = (
            f"tenants/{tenant_id}/jobs/{job_id}"
            f"/screening/{screening_run_id}-reranked.json"
        )
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=artifact_key,
            Body=json.dumps({
                "screening_run_id": screening_run_id,
                "tenant_id": tenant_id,
                "job_id": job_id,
                "phase": "phase3",
                "candidates": final_candidates,
            }, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Artifacts written to s3://%s/%s", S3_BUCKET, artifact_key)

    finally:
        mongo_client.close()


def lambda_handler(event: dict, context: object) -> dict:
    """SQS trigger entry point."""
    batch_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "?")
        try:
            body = json.loads(record["body"])
            _run_screening(
                screening_run_id=body["screening_run_id"],
                tenant_id=body["tenant_id"],
                job_id=body["job_id"],
            )
        except Exception as exc:
            logger.error("Screening failed for message %s: %s", message_id, exc)
            batch_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_failures}
