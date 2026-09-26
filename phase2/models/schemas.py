"""
Phase 2 data schemas.

Plain dataclasses — no heavy dependencies like Pydantic.
These define the shape of data flowing through the Phase 2 pipeline and
the structure of documents stored in MongoDB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Indexing ──────────────────────────────────────────────────────────────────

@dataclass
class CandidateChunk:
    """
    One document stored in the MongoDB `candidate_chunks` collection.

    Each document represents a single meaningful section chunk of a resume.
    The `embedding` field is the 1024-dimensional Voyage AI vector.
    The `content_hash` is used for idempotent re-indexing.
    """
    candidate_id: str           # e.g. "john-doe"  (derived from PDF filename)
    chunk_id: str               # e.g. "john-doe_experience_00"  (globally unique)
    source_key: str             # e.g. "extracted/<textract-job-id>.json"
    chunk_index: int            # 0-based index within the candidate's chunks
    section: str                # e.g. "experience", "skills", "education"
    text: str                   # The chunk text used for retrieval
    embedding_model: str        # e.g. "voyage-4-large"
    embedding_dimensions: int   # e.g. 1024
    embedding: List[float]      # The 1024-float embedding vector
    content_hash: str           # SHA-256 of the full resume text (for idempotency)
    metadata: Dict[str, Any] = field(default_factory=dict)  # page_start, page_end, etc.

    def to_mongo_doc(self) -> dict:
        """Serialize to a MongoDB-ready document dict. Uses chunk_id as _id."""
        return {
            "_id": self.chunk_id,
            "candidate_id": self.candidate_id,
            "chunk_id": self.chunk_id,
            "source_key": self.source_key,
            "chunk_index": self.chunk_index,
            "section": self.section,
            "text": self.text,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "embedding": self.embedding,
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }


# ─── Retrieval ─────────────────────────────────────────────────────────────────

@dataclass
class MatchedChunk:
    """A chunk that contributed to a candidate's retrieval score."""
    chunk_id: str
    section: str


@dataclass
class RetrievalResult:
    """
    Per-candidate retrieval result with full provenance.

    Preserves which retrieval method(s) found this candidate and which
    chunks were responsible — critical for Phase 3/4 explainability.
    """
    candidate_id: str
    hybrid_score: float         # Accumulated RRF score
    lexical_rank: Optional[int] # Best rank in BM25 results; None if not found lexically
    vector_rank: Optional[int]  # Best rank in vector results; None if not found semantically
    matched_chunks: List[MatchedChunk]
    source_key: str             # The Phase 1 S3 key, e.g. "extracted/<job-id>.json"

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "hybrid_score": round(self.hybrid_score, 6),
            "retrieval": {
                "lexical_rank": self.lexical_rank,
                "vector_rank": self.vector_rank,
            },
            "matched_chunks": [
                {"chunk_id": c.chunk_id, "section": c.section}
                for c in self.matched_chunks
            ],
            "source_key": self.source_key,
        }


@dataclass
class HybridSearchOutput:
    """
    Complete output for one job description search.
    Written to outputs/<job-id>-retrieval.json and consumed by Phase 3.
    """
    job_id: str
    retrieval_method: str
    embedding_model: str
    embedding_dimensions: int
    parameters: Dict[str, Any]
    candidates: List[RetrievalResult]

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "retrieval_method": self.retrieval_method,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "parameters": self.parameters,
            "total_candidates": len(self.candidates),
            "candidates": [c.to_dict() for c in self.candidates],
        }
