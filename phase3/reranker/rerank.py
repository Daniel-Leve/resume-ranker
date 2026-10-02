"""
Core Reranking Logic for Phase 3.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

from phase3 import config
from phase3.models.schemas import Phase3Output, RerankedCandidate
from phase3.reranker.document_builder import build_candidate_document
from phase3.reranker.voyage_reranker import rerank_documents

logger = logging.getLogger(__name__)


def generate_evaluation_report(
    job_id: str,
    output_dir: Path,
    candidates: List[RerankedCandidate],
    failed_candidates: List[str],
    processing_time_sec: float,
    model: str,
    input_count: int,
) -> None:
    """Generate the evaluation summary JSON."""
    top_5 = []
    for c in candidates[:5]:
        top_5.append({
            "candidate_id": c.candidate_id,
            "rerank_score": c.rerank_score,
            "rerank_rank": c.rerank_rank,
            "rank_change": c.rank_change,
        })
        
    score_distribution = {
        "min": min([c.rerank_score for c in candidates]) if candidates else 0.0,
        "max": max([c.rerank_score for c in candidates]) if candidates else 0.0,
        "avg": (sum(c.rerank_score for c in candidates) / len(candidates)) if candidates else 0.0,
    }

    report = {
        "job_id": job_id,
        "phase": "phase3",
        "model_used": model,
        "processing_time_sec": round(processing_time_sec, 2),
        "candidates_received_from_phase2": input_count,
        "candidates_reranked": len(candidates),
        "candidates_failed": len(failed_candidates),
        "failed_candidate_ids": failed_candidates,
        "score_distribution": score_distribution,
        "top_5_candidates": top_5,
        "disclaimer": (
            "This report evaluates system mechanics, not AI model accuracy. "
            "Accuracy evaluation requires a labeled golden dataset."
        )
    }

    out_path = output_dir / f"{job_id}-rerank-evaluation.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved evaluation report to %s", out_path)


def run_reranking_pipeline(
    job_file: str,
    input_json: str,
    output_dir: str = "outputs",
    top_k: Optional[int] = None,
    model: Optional[str] = None,
    max_doc_chars: Optional[int] = None,
) -> Phase3Output:
    """Execute the Phase 3 semantic reranking pipeline."""
    start_time = time.time()
    
    # ── Configurations ─────────────────────────────────────────────────────────
    final_top_k = top_k if top_k is not None else config.RERANK_TOP_K
    used_model = model or config.VOYAGE_RERANK_MODEL
    max_chars = max_doc_chars or config.RERANK_MAX_DOCUMENT_CHARS
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # ── Job Description ────────────────────────────────────────────────────────
    jd_path = Path(job_file)
    if not jd_path.exists():
        raise FileNotFoundError(f"Job description not found: {jd_path}")
    
    job_id = jd_path.stem
    jd_text = jd_path.read_text(encoding="utf-8").strip()
    
    # ── Phase 2 Output ─────────────────────────────────────────────────────────
    in_path = Path(input_json)
    if not in_path.exists():
        raise FileNotFoundError(f"Phase 2 retrieval JSON not found: {in_path}")
        
    p2_data = json.loads(in_path.read_text(encoding="utf-8"))
    if p2_data.get("job_id") != job_id:
        logger.warning(
            "Mismatched job_id! JD=%s, Phase2 JSON=%s", job_id, p2_data.get("job_id")
        )
        
    raw_candidates = p2_data.get("candidates", [])
    candidate_count_input = len(raw_candidates)
    
    logger.info("=== Phase 3 Semantic Reranking ===")
    logger.info("Job ID: %s", job_id)
    logger.info("Model:  %s", used_model)
    logger.info("Input candidates: %d", candidate_count_input)
    
    # Track Phase 2 rank mapping
    # Since Phase 2 results are an ordered array, index + 1 is the Phase 2 rank.
    p2_ranks: Dict[str, int] = {}
    candidates_to_process: List[RerankedCandidate] = []
    
    for idx, c_dict in enumerate(raw_candidates):
        cid = c_dict["candidate_id"]
        p2_ranks[cid] = idx + 1
        candidates_to_process.append(RerankedCandidate.from_phase2_dict(c_dict))

    # ── Connect to MongoDB ─────────────────────────────────────────────────────
    import certifi
    mongo_client = MongoClient(
        config.MONGODB_URI, 
        serverSelectionTimeoutMS=15000,
        tlsCAFile=certifi.where()
    )
    failed_candidates: List[str] = []
    
    try:
        mongo_client.admin.command("ping")
        collection = mongo_client[config.MONGODB_DATABASE][config.MONGODB_COLLECTION]
        logger.info("Connected to MongoDB Atlas.")
        
        # ── Reconstruct Documents ──────────────────────────────────────────────
        valid_candidates: List[RerankedCandidate] = []
        document_texts: List[str] = []
        
        for cand in candidates_to_process:
            doc = build_candidate_document(collection, cand.candidate_id, max_chars)
            if not doc.text.strip():
                logger.error(
                    "Candidate %s has no text in MongoDB. Marking as failed.", 
                    cand.candidate_id
                )
                failed_candidates.append(cand.candidate_id)
                continue
                
            cand.document_chunks = doc.chunk_ids
            valid_candidates.append(cand)
            document_texts.append(doc.text)
            
        # ── Call Reranker API ──────────────────────────────────────────────────
        if not document_texts:
            raise RuntimeError("No valid candidate documents constructed. Aborting.")
            
        logger.info("Sending %d documents to Voyage rerank API...", len(document_texts))
        
        # By default Voyage top_k acts as a filter. If final_top_k is -1, return all.
        api_top_k = final_top_k if final_top_k > 0 else len(document_texts)
        
        # We send all valid candidate docs in one batch
        rerank_results = rerank_documents(
            query=jd_text,
            documents=document_texts,
            model=used_model,
            top_k=api_top_k
        )
        
        # ── Process Results ────────────────────────────────────────────────────
        final_candidates: List[RerankedCandidate] = []
        
        for i, res in enumerate(rerank_results):
            # 'index' maps to the original position in the documents array
            original_idx = res["index"]
            score = res["relevance_score"]
            
            cand = valid_candidates[original_idx]
            cand.rerank_score = score
            cand.rerank_rank = i + 1
            
            # Rank change: positive means they moved up (closer to #1)
            # Example: P2 rank = 7, P3 rank = 2 -> rank_change = +5
            p2_rank = p2_ranks[cand.candidate_id]
            cand.rank_change = p2_rank - cand.rerank_rank
            
            final_candidates.append(cand)
            
    finally:
        mongo_client.close()

    # ── Finalize Output ────────────────────────────────────────────────────────
    # The output from Voyage is already sorted by relevance_score descending.
    # Just in case, we'll ensure it:
    final_candidates.sort(key=lambda c: c.rerank_score, reverse=True)
    
    # Re-verify ranks after any potential re-sort
    for i, c in enumerate(final_candidates):
        c.rerank_rank = i + 1
        c.rank_change = p2_ranks[c.candidate_id] - c.rerank_rank
        
    output = Phase3Output(
        job_id=job_id,
        retrieval_method="hybrid",
        rerank_model=used_model,
        candidate_count_input=candidate_count_input,
        candidate_count_output=len(final_candidates),
        candidates=final_candidates,
    )
    
    # ── Write Output JSON ──────────────────────────────────────────────────────
    out_path = out_dir / f"{job_id}-reranked.json"
    out_path.write_text(json.dumps(output.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    
    # ── Write Evaluation JSON ──────────────────────────────────────────────────
    processing_time = time.time() - start_time
    generate_evaluation_report(
        job_id=job_id,
        output_dir=out_dir,
        candidates=final_candidates,
        failed_candidates=failed_candidates,
        processing_time_sec=processing_time,
        model=used_model,
        input_count=candidate_count_input,
    )
    
    # ── Summary ────────────────────────────────────────────────────────────────
    sep = "─" * 52
    logger.info(sep)
    logger.info("Phase 3 complete for job: %s", job_id)
    logger.info("  Input candidates:  %3d", candidate_count_input)
    logger.info("  Successfully reranked: %3d", len(final_candidates))
    logger.info("  Failed:            %3d", len(failed_candidates))
    logger.info("  Reranked Output:   %s", out_path)
    logger.info(sep)

    return output
