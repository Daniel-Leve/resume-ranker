"""
Reciprocal Rank Fusion (RRF) for Phase 2 hybrid retrieval.

RRF merges a BM25-ranked list and a vector-similarity-ranked list into a
single fused ranking without requiring score normalisation across the two
retrieval methods.

Formula (Cormack et al., 2009):
    RRF_score(doc) = Σ  1 / (rank_i + k)
    where i ranges over retrieval methods in which the document appears.

k = 60  (the standard constant; keeps high-rank items dominant without
          excessively penalising items appearing later in a short list).

Design notes
------------
- Operates at the *chunk* level but deduplicates at the *candidate* level.
- A candidate appearing in multiple chunks accumulates score from each
  chunk's rank.  This rewards candidates whose content is broadly relevant.
- The stored ``lexical_rank`` / ``vector_rank`` reflect the *best* (minimum)
  rank of any of the candidate's chunks in that retrieval method.
- Ranks are stored as None — never invented — when a candidate does not
  appear in a retrieval method.  This preserves honest provenance for Phase 3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from phase2.retrieval.lexical_search import ChunkHit

logger = logging.getLogger(__name__)


def rrf_score(rank: int, k: int = 60) -> float:
    """
    RRF score contribution for a single rank position.

    Args:
        rank: 1-based position in the ranked list.
        k:    Smoothing constant (default 60).

    Returns:
        1.0 / (rank + k)
    """
    return 1.0 / (rank + k)


@dataclass
class CandidateProvenance:
    """Accumulated retrieval evidence for a single candidate across methods."""
    candidate_id: str
    rrf_score: float = 0.0
    # Best (lowest) rank position in each retrieval method; None = not found there.
    lexical_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    # chunk_id → section label for every chunk that contributed to this result.
    matched_chunks: Dict[str, str] = field(default_factory=dict)
    source_key: str = ""          # Phase 1 S3 key for traceability


def fuse_results(
    lexical_results: List[ChunkHit],
    vector_results: List[ChunkHit],
    final_top_k: int,
    rrf_k: int = 60,
) -> List[CandidateProvenance]:
    """
    Combine chunk-level BM25 and vector results using Reciprocal Rank Fusion.

    Args:
        lexical_results: Chunk hits from Atlas Search, ordered best-first.
        vector_results:  Chunk hits from Atlas Vector Search, ordered best-first.
        final_top_k:     Maximum number of unique candidates to return.
        rrf_k:           RRF smoothing constant (default 60).

    Returns:
        List of CandidateProvenance sorted by rrf_score descending,
        truncated to ``final_top_k`` entries.
    """
    candidates: Dict[str, CandidateProvenance] = {}

    def _get(candidate_id: str, source_key: str) -> CandidateProvenance:
        """Retrieve or create a CandidateProvenance for the given candidate."""
        if candidate_id not in candidates:
            candidates[candidate_id] = CandidateProvenance(
                candidate_id=candidate_id,
                source_key=source_key,
            )
        prov = candidates[candidate_id]
        # Capture source_key on first encounter
        if not prov.source_key and source_key:
            prov.source_key = source_key
        return prov

    # ── Accumulate lexical ranks ───────────────────────────────────────────────
    for rank, hit in enumerate(lexical_results, start=1):
        prov = _get(hit.candidate_id, hit.source_key)
        prov.rrf_score += rrf_score(rank, rrf_k)
        if prov.lexical_rank is None or rank < prov.lexical_rank:
            prov.lexical_rank = rank
        prov.matched_chunks[hit.chunk_id] = hit.section

    # ── Accumulate vector ranks ────────────────────────────────────────────────
    for rank, hit in enumerate(vector_results, start=1):
        prov = _get(hit.candidate_id, hit.source_key)
        prov.rrf_score += rrf_score(rank, rrf_k)
        if prov.vector_rank is None or rank < prov.vector_rank:
            prov.vector_rank = rank
        prov.matched_chunks[hit.chunk_id] = hit.section

    # ── Sort and trim ──────────────────────────────────────────────────────────
    ranked = sorted(candidates.values(), key=lambda p: p.rrf_score, reverse=True)
    top = ranked[:final_top_k]

    lex_unique = len({h.candidate_id for h in lexical_results})
    vec_unique = len({h.candidate_id for h in vector_results})
    both = len(
        {h.candidate_id for h in lexical_results}
        & {h.candidate_id for h in vector_results}
    )

    logger.info(
        "RRF fusion: BM25 %d chunks (%d unique cands) + vector %d chunks (%d unique cands) "
        "→ overlap %d → %d total unique → top %d returned",
        len(lexical_results), lex_unique,
        len(vector_results), vec_unique,
        both, len(candidates), len(top),
    )
    return top
