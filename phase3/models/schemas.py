"""
Phase 3 Data Schemas
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MatchedChunk:
    chunk_id: str
    section: str


@dataclass
class Phase2Provenance:
    hybrid_score: float
    lexical_rank: Optional[int]
    vector_rank: Optional[int]
    matched_chunks: List[MatchedChunk]

    @classmethod
    def from_dict(cls, data: dict) -> "Phase2Provenance":
        return cls(
            hybrid_score=data.get("hybrid_score", 0.0),
            lexical_rank=data.get("retrieval", {}).get("lexical_rank"),
            vector_rank=data.get("retrieval", {}).get("vector_rank"),
            matched_chunks=[
                MatchedChunk(chunk_id=mc["chunk_id"], section=mc["section"])
                for mc in data.get("matched_chunks", [])
            ],
        )

    def to_dict(self) -> dict:
        return {
            "hybrid_score": self.hybrid_score,
            "lexical_rank": self.lexical_rank,
            "vector_rank": self.vector_rank,
            "matched_chunks": [
                {"chunk_id": mc.chunk_id, "section": mc.section}
                for mc in self.matched_chunks
            ],
        }


@dataclass
class RerankedCandidate:
    candidate_id: str
    source_key: str
    phase2: Phase2Provenance
    
    # Reranking fields (populated later)
    rerank_score: float = 0.0
    rerank_rank: int = 0
    rank_change: int = 0
    document_chunks: List[str] = field(default_factory=list)

    @classmethod
    def from_phase2_dict(cls, data: dict) -> "RerankedCandidate":
        """Construct from a candidate object in the Phase 2 output JSON."""
        return cls(
            candidate_id=data["candidate_id"],
            source_key=data.get("source_key", ""),
            phase2=Phase2Provenance.from_dict(data),
        )

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "rerank_rank": self.rerank_rank,
            "rerank_score": round(self.rerank_score, 6),
            "rank_change": self.rank_change,
            "phase2": self.phase2.to_dict(),
            "source_key": self.source_key,
            "document_chunks": self.document_chunks,
        }


@dataclass
class Phase3Output:
    job_id: str
    retrieval_method: str = "hybrid"
    rerank_model: str = ""
    candidate_count_input: int = 0
    candidate_count_output: int = 0
    candidates: List[RerankedCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "phase": "phase3",
            "retrieval_method": self.retrieval_method,
            "rerank_model": self.rerank_model,
            "candidate_count_input": self.candidate_count_input,
            "candidate_count_output": self.candidate_count_output,
            "candidates": [c.to_dict() for c in self.candidates],
        }
