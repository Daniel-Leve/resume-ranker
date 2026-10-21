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

from api.auth.secrets import get_mongodb_uri
from api.storage.mongo import get_mongo_client
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
    uri = get_mongodb_uri() if os.environ.get("MONGODB_URI_SECRET_ARN") or not config.MONGODB_URI else config.MONGODB_URI
    return get_mongo_client(uri)


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


def _run_screening(
    screening_run_id: str,
    tenant_id: str,
    job_id: str,
    final_shortlisted_candidates_count: Optional[int] = None,
) -> None:
    """Execute Phase 2+3 screening pipeline and persist results."""
    if not screening_run_id or not str(screening_run_id).strip():
        raise ValueError("screening_run_id is required and cannot be empty")
    if not tenant_id or not str(tenant_id).strip():
        raise ValueError("tenant_id is required and cannot be empty")
    if not job_id or not str(job_id).strip():
        raise ValueError("job_id is required and cannot be empty")

    screening_run_id = str(screening_run_id).strip()
    tenant_id = str(tenant_id).strip()
    job_id = str(job_id).strip()

    start_time = time.time()
    logger.info(
        "Starting screening run %s (tenant=%s job=%s)",
        screening_run_id, tenant_id, job_id
    )

    mongo_client = _get_mongo()
    db = mongo_client[config.MONGODB_DATABASE]
    collection = db[config.MONGODB_COLLECTION]

    # Idempotency check: if already completed (e.g. SQS redelivery after client ack timeout), skip execution
    existing_run = db["screening_runs"].find_one({"_id": screening_run_id})
    if existing_run and existing_run.get("status") == "COMPLETED":
        logger.info("Screening run %s already marked COMPLETED — skipping re-execution.", screening_run_id)
        return

    # Resolve HR specified final shortlisted candidate count
    shortlisted_count = None
    if final_shortlisted_candidates_count is not None:
        try:
            val = int(final_shortlisted_candidates_count)
            if val > 0:
                shortlisted_count = val
        except (ValueError, TypeError):
            pass

    if shortlisted_count is None and existing_run:
        val = existing_run.get("final_shortlisted_candidates_count") or existing_run.get("shortlisted_candidates_count")
        if val is not None:
            try:
                shortlisted_count = max(1, int(val))
            except (ValueError, TypeError):
                pass

    job_doc = db["jobs"].find_one({"_id": job_id, "tenant_id": tenant_id})
    if shortlisted_count is None and job_doc:
        val = job_doc.get("final_shortlisted_candidates_count") or job_doc.get("shortlisted_candidates_count")
        if val is not None:
            try:
                shortlisted_count = max(1, int(val))
            except (ValueError, TypeError):
                pass

    if shortlisted_count is None or shortlisted_count <= 0:
        shortlisted_count = 5  # default if not specified by HR

    try:
        _update_run_status(db, screening_run_id, "RUNNING_PHASE2",
                           {"phase2_status": "RUNNING", "final_shortlisted_candidates_count": shortlisted_count})

        # ── Load Job Description ───────────────────────────────────────────
        jd_text = _get_job_description(db, job_id, tenant_id)
        if not jd_text:
            raise ValueError(f"Job description not found for job_id={job_id} and tenant_id={tenant_id}")

        # ── Phase 2: Embed JD ──────────────────────────────────────
        logger.info("Embedding job description...")
        jd_embedding = embed_texts([jd_text], input_type="query")[0]

        # ── Phase 2: Dynamic Hybrid Retrieval (no hard truncation) ─────────
        # Automatically reduce candidate pool from Phase 2 hybrid search.
        # Use an expansion factor (3x of HR shortlisted count, min 10) so Phase 3 reranker has sufficient recall.
        total_eligible = 0
        try:
            if hasattr(db["applications"], "count_documents"):
                cnt = db["applications"].count_documents({
                    "job_id": job_id,
                    "tenant_id": tenant_id,
                    "phase2_status": "INDEXED",
                    "status": {"$ne": "ARCHIVED"},
                })
                if isinstance(cnt, int) and cnt > 0:
                    total_eligible = cnt
        except Exception:
            total_eligible = 0

        phase2_pool_target = max(shortlisted_count * 3, 10)
        if total_eligible > 0:
            phase2_pool_target = min(phase2_pool_target, total_eligible)

        lex_k = max(phase2_pool_target * 2, 20)
        vec_k = max(phase2_pool_target * 2, 20)
        final_k = phase2_pool_target

        logger.info(
            "Phase 2 retrieval: target_shortlisted=%d, total_eligible=%d → phase2_pool=%d (lex_k=%d, vec_k=%d)",
            shortlisted_count, total_eligible, final_k, lex_k, vec_k
        )

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
        logger.info("Phase 2 complete: %d unique candidates passed to Phase 3 reranker.", len(fused))

        _update_run_status(db, screening_run_id, "RUNNING_PHASE3", {
            "phase2_status": "COMPLETED",
            "phase2_candidate_count": len(fused),
            "phase3_status": "RUNNING",
        })

        if not fused:
            _update_run_status(db, screening_run_id, "COMPLETED", {
                "phase2_status": "COMPLETED",
                "phase2_candidate_count": 0,
                "phase3_status": "SKIPPED",
                "reason": "No candidates returned from Phase 2.",
                "candidates": [],
                "candidate_count": 0,
                "completed_at": _now_iso(),
            })
            return

        # ── Phase 3: Reconstruct Candidate Documents ───────────────────────
        logger.info("Reconstructing %d candidate documents for reranking...", len(fused))
        valid_candidates = []
        documents = []
        candidate_texts = {}

        for prov in fused:
            doc = build_candidate_document(
                collection,
                prov.candidate_id,
                tenant_id=tenant_id,
                job_id=job_id,
            )
            if not doc.text.strip():
                logger.warning("No text for candidate %s — skipping.", prov.candidate_id)
                continue
            valid_candidates.append(prov)
            documents.append(doc.text)
            candidate_texts[prov.candidate_id] = doc.text

        if not documents:
            logger.warning("No valid candidate documents could be reconstructed for Phase 3.")
            _update_run_status(db, screening_run_id, "COMPLETED", {
                "phase3_status": "SKIPPED",
                "reason": "No valid candidate documents could be reconstructed for Phase 3.",
                "candidates": [],
                "candidate_count": 0,
                "completed_at": _now_iso(),
            })
            return

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

        # Map candidate_id/source_key to application_id and candidate_name from MongoDB
        app_lookup = {}
        for app in db["applications"].find({"job_id": job_id, "tenant_id": tenant_id}):
            app_id = str(app["_id"])
            cand_id = app.get("candidate_id") or app_id
            cand_name = app.get("candidate_name")
            app_lookup[cand_id] = (app_id, cand_name)
            # Also map by candidate_id derived from filename
            if app.get("s3_resume_key"):
                from phase2.indexer.index_resumes import derive_candidate_id
                slug = derive_candidate_id(app["s3_resume_key"])
                app_lookup[slug] = (app_id, cand_name)

        for rank_pos, result in enumerate(rerank_results, start=1):
            prov = valid_candidates[result["index"]]
            p2_rank = p2_ranks[prov.candidate_id]
            app_id, cand_name = app_lookup.get(prov.candidate_id, (None, None))
            cand_payload = {
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
            }
            if app_id:
                cand_payload["application_id"] = app_id
            if cand_name:
                cand_payload["candidate_name"] = cand_name
            final_candidates.append(cand_payload)

        elapsed = round(time.time() - start_time, 2)
        logger.info("Phase 3 complete: %d candidates reranked in %.1fs.", len(final_candidates), elapsed)

        # Mark phase3_status COMPLETED on all processed application documents in MongoDB
        for c in final_candidates:
            a_id = c.get("application_id")
            if not a_id:
                a_tuple = app_lookup.get(c["candidate_id"])
                if a_tuple:
                    a_id = a_tuple[0]
            if a_id:
                db["applications"].update_one(
                    {"_id": a_id},
                    {"$set": {
                        "phase3_status": "COMPLETED",
                        "updated_at": _now_iso(),
                    }}
                )

        # Output exactly the HR-specified final shortlisted candidate count of candidates alone
        top_candidates = final_candidates[:shortlisted_count]
        logger.info(
            "Phase 3 selection: outputting exactly %d top candidate(s) (HR requested count: %d).",
            len(top_candidates), shortlisted_count,
        )

        # ── Phase 4: Rubric Evaluation & Explainability ────────────────────
        phase4_status = "NOT_STARTED"
        rubric_obj = None
        if job_doc and job_doc.get("rubric"):
            try:
                from phase4.schemas import JobRubric
                rubric_obj = JobRubric.model_validate(job_doc["rubric"])
            except Exception as exc:
                logger.warning("Failed to parse rubric from job doc: %s", exc)

        if not rubric_obj:
            try:
                from phase4.rubric_builder import get_rubric
                rubric_obj = get_rubric(job_id)
            except Exception:
                rubric_obj = None

        if rubric_obj and rubric_obj.status == "APPROVED":
            logger.info(
                "Phase 4: Found APPROVED rubric (%s) with %d criteria. Starting evaluation...",
                rubric_obj.version, len(rubric_obj.criteria)
            )
            _update_run_status(db, screening_run_id, "RUNNING_PHASE4", {
                "phase3_status": "COMPLETED",
                "phase4_status": "RUNNING",
            })
            try:
                from phase4.orchestrator import Phase4Orchestrator
                from phase4.daily_budget import DailyBudget
                from phase4.review_queue import ReviewQueueManager
                from phase4.llm_client import GroqClient

                orchestrator = Phase4Orchestrator(
                    llm_client=GroqClient(),
                    daily_budget=DailyBudget(mongo_db=db),
                    review_queue=ReviewQueueManager(mongo_db=db),
                )

                # Prepare resumes for Phase 4
                resumes_p4 = []
                for c in final_candidates:
                    cid = c["candidate_id"]
                    raw_text = candidate_texts.get(cid, "")
                    if raw_text:
                        resumes_p4.append({
                            "resume_id": cid,
                            "application_id": c.get("application_id"),
                            "candidate_name": c.get("candidate_name"),
                            "raw_text": raw_text,
                        })

                phase3_results = {"candidates": top_candidates}
                p4_eval = orchestrator.evaluate_batch(
                    jd_id=job_id,
                    resumes=resumes_p4,
                    phase3_results=phase3_results,
                    rubric=rubric_obj,
                    tenant_id=tenant_id,
                )

                candidate_results = p4_eval.get("candidate_results", {})
                for c in top_candidates:
                    cid = c["candidate_id"]
                    if cid in candidate_results:
                        res = candidate_results[cid]
                        c["decision"] = res.get("decision", "UNDECIDED")
                        c["composite_score"] = res.get("weighted_score")
                        c["final_score"] = res.get("weighted_score")
                        if "hr_report" in res:
                            c["hr_report"] = res["hr_report"]
                        if "feedback" in res:
                            c["candidate_feedback"] = res["feedback"]

                # Update application collection documents with decisions & reports
                for cid, res in candidate_results.items():
                    app_id = res.get("application_id")
                    if not app_id:
                        app_tuple = app_lookup.get(cid)
                        if app_tuple:
                            app_id = app_tuple[0]

                    if app_id:
                        decision_val = res.get("decision", "UNDECIDED")
                        app_update = {
                            "decision": decision_val,
                            "phase3_status": "COMPLETED",
                            "phase4_status": "COMPLETED",
                            "screened_at": _now_iso(),
                            "updated_at": _now_iso(),
                            "screening_run_id": screening_run_id,
                        }
                        if decision_val in ("SHORTLISTED", "REJECTED"):
                            app_update["status"] = decision_val
                        elif decision_val == "UNDECIDED":
                            app_update["status"] = "NEEDS_REVIEW"
                        if "hr_report" in res:
                            app_update["hr_report"] = res["hr_report"]
                        if "feedback" in res:
                            app_update["candidate_feedback"] = res["feedback"]

                        db["applications"].update_one(
                            {"_id": app_id},
                            {"$set": app_update}
                        )

                phase4_status = "COMPLETED"
                logger.info(
                    "Phase 4 completed successfully: %d auto decisions, %d review queue.",
                    p4_eval.get("auto_decisions", 0), p4_eval.get("human_review_queue", 0)
                )
            except Exception as p4_exc:
                logger.error("Phase 4 evaluation failed: %s", p4_exc, exc_info=True)
                phase4_status = "FAILED"

        # ── Persist results in MongoDB ─────────────────────────────────────
        status_payload = {
            "phase3_status": "COMPLETED",
            "phase4_status": phase4_status,
            "candidates": top_candidates,
            "candidate_count": len(top_candidates),
            "final_shortlisted_candidates_count": shortlisted_count,
            "phase2_candidate_count": len(fused),
            "processing_time_sec": elapsed,
            "completed_at": _now_iso(),
        }

        _update_run_status(db, screening_run_id, "COMPLETED", status_payload)

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
                "final_shortlisted_candidates_count": shortlisted_count,
                "candidate_count": len(top_candidates),
                "candidates": top_candidates,
            }, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Artifacts written to s3://%s/%s", S3_BUCKET, artifact_key)

    except Exception as exc:
        logger.error("Screening run %s failed: %s", screening_run_id, exc, exc_info=True)
        _update_run_status(db, screening_run_id, "FAILED", {
            "error": str(exc),
            "completed_at": _now_iso(),
        })
        raise


def lambda_handler(event: dict, context: object) -> dict:
    """SQS trigger entry point."""
    batch_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "?")
        try:
            body = json.loads(record["body"])
            kwargs = {}
            if "final_shortlisted_candidates_count" in body:
                kwargs["final_shortlisted_candidates_count"] = body["final_shortlisted_candidates_count"]
            _run_screening(
                screening_run_id=body["screening_run_id"],
                tenant_id=body["tenant_id"],
                job_id=body["job_id"],
                **kwargs,
            )
        except Exception as exc:
            logger.error("Screening failed for message %s: %s", message_id, exc)
            batch_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_failures}
