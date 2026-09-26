"""
Phase 2 hybrid search — combines BM25 and vector retrieval with RRF.

Entry point:  python -m phase2.search --job jobs/backend-engineer-001.txt [options]

Pipeline
--------
1. Read job description from file.
2. Normalise text (collapse whitespace).
3. Embed with Voyage AI  (input_type="query").
4. Run MongoDB Atlas Search  (BM25, lexical).
5. Run MongoDB Atlas Vector Search  (cosine, semantic).
6. Combine results with Reciprocal Rank Fusion.
7. Deduplicate by candidate_id.
8. Write ranked candidates to outputs/<job-id>-retrieval.json.

Output format
-------------
See models/schemas.py → HybridSearchOutput.to_dict() for the exact schema.
The output is designed for consumption by Phase 3.

Security
--------
Job description text is not logged in full — only length and job_id are logged.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

from pymongo import MongoClient

from phase2 import config
from phase2.indexer.embedder import embed_texts
from phase2.models.schemas import HybridSearchOutput, MatchedChunk, RetrievalResult
from phase2.retrieval.fusion import CandidateProvenance, fuse_results
from phase2.retrieval.lexical_search import lexical_search
from phase2.retrieval.vector_search import vector_search

logger = logging.getLogger(__name__)


def _normalize_jd(text: str) -> str:
    """Normalise job description text: collapse whitespace, strip."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _provenance_to_result(prov: CandidateProvenance) -> RetrievalResult:
    """Convert a CandidateProvenance into a RetrievalResult for output."""
    matched = [
        MatchedChunk(chunk_id=cid, section=sec)
        for cid, sec in prov.matched_chunks.items()
    ]
    return RetrievalResult(
        candidate_id=prov.candidate_id,
        hybrid_score=prov.rrf_score,
        lexical_rank=prov.lexical_rank,
        vector_rank=prov.vector_rank,
        matched_chunks=matched,
        source_key=prov.source_key,
    )


def hybrid_search(
    job_file: str,
    top_k: Optional[int] = None,
    output_dir: str = "outputs",
    lexical_top_k: Optional[int] = None,
    vector_top_k: Optional[int] = None,
) -> HybridSearchOutput:
    """
    Execute hybrid retrieval for a job description file.

    Args:
        job_file:      Path to the job description ``.txt`` file.
        top_k:         Maximum unique candidates to return.
        output_dir:    Directory where ``<job-id>-retrieval.json`` is written.
        lexical_top_k: Override for BM25 chunk retrieval depth.
        vector_top_k:  Override for vector search chunk retrieval depth.

    Returns:
        HybridSearchOutput with provenance-annotated candidates.
    """
    final_k: int = top_k or config.FINAL_TOP_K
    lex_k: int = lexical_top_k or config.LEXICAL_TOP_K
    vec_k: int = vector_top_k or config.VECTOR_TOP_K

    # ── Job description ────────────────────────────────────────────────────────
    jd_path = Path(job_file)
    if not jd_path.exists():
        raise FileNotFoundError(f"Job description not found: {jd_path}")

    job_id = jd_path.stem  # e.g. "backend-engineer-001"
    jd_raw = jd_path.read_text(encoding="utf-8")
    jd_text = _normalize_jd(jd_raw)

    logger.info("=== Phase 2 Hybrid Search ===")
    logger.info("Job ID:  %s", job_id)
    logger.info("JD size: %d characters", len(jd_text))
    logger.info(
        "Params:  lex_top_k=%d  vec_top_k=%d  final_top_k=%d  rrf_k=%d",
        lex_k, vec_k, final_k, config.RRF_K,
    )

    # ── Embed job description ──────────────────────────────────────────────────
    logger.info("Embedding JD with %s (input_type=query)...", config.VOYAGE_MODEL)
    jd_embedding: List[float] = embed_texts([jd_text], input_type="query")[0]

    # ── Connect MongoDB ────────────────────────────────────────────────────────
    mongo_client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=15_000)
    try:
        mongo_client.admin.command("ping")
        collection = mongo_client[config.MONGODB_DATABASE][config.MONGODB_COLLECTION]
        logger.info(
            "Connected to MongoDB: %s.%s",
            config.MONGODB_DATABASE, config.MONGODB_COLLECTION,
        )

        # ── Retrieve ───────────────────────────────────────────────────────────
        logger.info("Running BM25 (lexical) search, top_k=%d...", lex_k)
        lex_hits = lexical_search(collection, jd_text, top_k=lex_k)

        logger.info("Running vector (semantic) search, top_k=%d...", vec_k)
        vec_hits = vector_search(collection, jd_embedding, top_k=vec_k)

        # ── Fuse ───────────────────────────────────────────────────────────────
        fused = fuse_results(lex_hits, vec_hits, final_top_k=final_k, rrf_k=config.RRF_K)

    finally:
        mongo_client.close()

    # ── Build output ───────────────────────────────────────────────────────────
    candidates = [_provenance_to_result(p) for p in fused]

    output = HybridSearchOutput(
        job_id=job_id,
        retrieval_method="hybrid",
        embedding_model=config.VOYAGE_MODEL,
        embedding_dimensions=config.VOYAGE_EMBEDDING_DIMENSIONS,
        parameters={
            "lexical_top_k": lex_k,
            "vector_top_k": vec_k,
            "final_top_k": final_k,
            "rrf_k": config.RRF_K,
        },
        candidates=candidates,
    )

    # ── Write output ───────────────────────────────────────────────────────────
    out_path = Path(output_dir) / f"{job_id}-retrieval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ── Summary ────────────────────────────────────────────────────────────────
    lex_candidate_ids = {h.candidate_id for h in lex_hits}
    vec_candidate_ids = {h.candidate_id for h in vec_hits}
    overlap = lex_candidate_ids & vec_candidate_ids

    sep = "─" * 52
    logger.info(sep)
    logger.info("Results for job: %s", job_id)
    logger.info("  BM25 unique candidates:    %3d", len(lex_candidate_ids))
    logger.info("  Vector unique candidates:  %3d", len(vec_candidate_ids))
    logger.info("  In both (overlap):         %3d", len(overlap))
    logger.info("  Final unique candidates:   %3d", len(candidates))
    logger.info("  Output:  %s", out_path)
    logger.info(sep)

    if len(candidates) < final_k:
        logger.warning(
            "Returned %d candidates (fewer than requested %d). "
            "Index more resumes to improve recall.",
            len(candidates), final_k,
        )

    return output


# ─── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phase2.search",
        description=(
            "Phase 2 hybrid search: BM25 + vector retrieval with RRF fusion "
            "for an initial candidate pool."
        ),
    )
    parser.add_argument(
        "--job",
        required=True,
        metavar="JOB_FILE",
        help="Path to job description .txt file (e.g. jobs/backend-engineer-001.txt).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        metavar="K",
        help=(
            f"Max unique candidates to return "
            f"(default: FINAL_TOP_K env var or {config.FINAL_TOP_K})."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        metavar="DIR",
        help="Directory for output JSON files (default: outputs/).",
    )
    parser.add_argument(
        "--lexical-top-k",
        type=int,
        default=None,
        metavar="K",
        help=(
            f"BM25 chunk retrieval depth "
            f"(default: LEXICAL_TOP_K env var or {config.LEXICAL_TOP_K})."
        ),
    )
    parser.add_argument(
        "--vector-top-k",
        type=int,
        default=None,
        metavar="K",
        help=(
            f"Vector search chunk retrieval depth "
            f"(default: VECTOR_TOP_K env var or {config.VECTOR_TOP_K})."
        ),
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

    try:
        config.validate()
    except EnvironmentError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    try:
        result = hybrid_search(
            job_file=args.job,
            top_k=args.top_k,
            output_dir=args.output_dir,
            lexical_top_k=args.lexical_top_k,
            vector_top_k=args.vector_top_k,
        )
        logger.info(
            "Done. %d candidate(s) written to outputs/%s-retrieval.json",
            len(result.candidates), result.job_id,
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Search interrupted by user.")
        sys.exit(130)
