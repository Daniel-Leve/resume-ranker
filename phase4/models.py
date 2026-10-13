"""
Phase 4 Data Schemas and Domain Models.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from phase4.config import EXPLANATION_VERSION, AUDIT_LIMITATIONS


@dataclass
class SupportingEvidence:
    chunk_id: str
    section: str
    excerpt: str
    relevance_keyword: Optional[str] = None
    content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.content_hash and self.excerpt:
            self.content_hash = hashlib.sha256(self.excerpt.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "chunk_id": self.chunk_id,
            "section": self.section,
            "excerpt": self.excerpt,
        }
        if self.relevance_keyword:
            data["relevance_keyword"] = self.relevance_keyword
        if self.content_hash:
            data["content_hash"] = self.content_hash
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SupportingEvidence":
        return cls(
            chunk_id=data.get("chunk_id", ""),
            section=data.get("section", ""),
            excerpt=data.get("excerpt", ""),
            relevance_keyword=data.get("relevance_keyword"),
            content_hash=data.get("content_hash"),
        )


@dataclass
class RequirementAlignment:
    requirement: str
    category: str  # "required", "preferred", "general"
    status: str  # "supported" or "not_established"
    supporting_chunks: List[str] = field(default_factory=list)
    evidence_excerpts: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement": self.requirement,
            "category": self.category,
            "status": self.status,
            "supporting_chunks": self.supporting_chunks,
            "evidence_excerpts": self.evidence_excerpts,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequirementAlignment":
        return cls(
            requirement=data.get("requirement", ""),
            category=data.get("category", "general"),
            status=data.get("status", "not_established"),
            supporting_chunks=data.get("supporting_chunks", []),
            evidence_excerpts=data.get("evidence_excerpts", []),
            rationale=data.get("rationale", ""),
        )


@dataclass
class JobRequirement:
    text: str
    category: str = "required"  # "required", "preferred", "general"
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "category": self.category,
            "keywords": self.keywords,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobRequirement":
        return cls(
            text=data.get("text", ""),
            category=data.get("category", "required"),
            keywords=data.get("keywords", []),
        )


@dataclass
class CandidateExplanation:
    candidate_id: str
    rerank_rank: int
    summary: str
    matched_sections: List[str] = field(default_factory=list)
    supporting_evidence: List[SupportingEvidence] = field(default_factory=list)
    requirement_alignment: List[RequirementAlignment] = field(default_factory=list)
    evidence_gaps: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=lambda: list(AUDIT_LIMITATIONS))
    application_id: Optional[str] = None
    candidate_name: Optional[str] = None
    rerank_score: Optional[float] = None
    explanation_version: str = EXPLANATION_VERSION

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "rerank_rank": self.rerank_rank,
            "summary": self.summary,
            "matched_sections": self.matched_sections,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "requirement_alignment": [r.to_dict() for r in self.requirement_alignment],
            "evidence_gaps": self.evidence_gaps,
            "limitations": self.limitations,
            "explanation_version": self.explanation_version,
        }
        if self.application_id:
            data["application_id"] = self.application_id
        if self.candidate_name:
            data["candidate_name"] = self.candidate_name
        if self.rerank_score is not None:
            data["rerank_score"] = self.rerank_score
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateExplanation":
        return cls(
            candidate_id=data["candidate_id"],
            rerank_rank=data.get("rerank_rank", 0),
            summary=data.get("summary", ""),
            matched_sections=data.get("matched_sections", []),
            supporting_evidence=[
                SupportingEvidence.from_dict(e) for e in data.get("supporting_evidence", [])
            ],
            requirement_alignment=[
                RequirementAlignment.from_dict(r) for r in data.get("requirement_alignment", [])
            ],
            evidence_gaps=data.get("evidence_gaps", []),
            limitations=data.get("limitations", list(AUDIT_LIMITATIONS)),
            application_id=data.get("application_id"),
            candidate_name=data.get("candidate_name"),
            rerank_score=data.get("rerank_score"),
            explanation_version=data.get("explanation_version", EXPLANATION_VERSION),
        )


@dataclass
class Phase4Report:
    job_id: str
    candidate_count: int
    candidates: List[CandidateExplanation]
    tenant_id: Optional[str] = None
    screening_run_id: Optional[str] = None
    explanation_version: str = EXPLANATION_VERSION
    generator_type: str = "deterministic"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "job_id": self.job_id,
            "phase": "phase4",
            "explanation_version": self.explanation_version,
            "generator_type": self.generator_type,
            "candidate_count": self.candidate_count,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.tenant_id:
            data["tenant_id"] = self.tenant_id
        if self.screening_run_id:
            data["screening_run_id"] = self.screening_run_id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Phase4Report":
        return cls(
            job_id=data.get("job_id", ""),
            candidate_count=data.get("candidate_count", len(data.get("candidates", []))),
            candidates=[CandidateExplanation.from_dict(c) for c in data.get("candidates", [])],
            tenant_id=data.get("tenant_id"),
            screening_run_id=data.get("screening_run_id"),
            explanation_version=data.get("explanation_version", EXPLANATION_VERSION),
            generator_type=data.get("generator_type", "deterministic"),
        )
