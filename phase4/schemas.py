"""
Phase 4 Schemas and Pydantic Models for Structured Validation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Rubric Schemas (4a) ──────────────────────────────────────────────────────

class RubricCriterion(BaseModel):
    id: str = Field(..., description="Unique criterion identifier e.g. c1, c2")
    description: str = Field(..., description="Clear requirement statement extracted from JD")
    type: Literal["must", "nice"] = Field(..., description="'must' for non-negotiable must-haves, 'nice' for preferred")
    weight: float = Field(..., ge=0.0, le=1.0, description="Normalized weight (must-haves typically weighted higher)")
    how_to_verify: str = Field(..., description="Guidance on what constitutes verifiable evidence in the resume")


class JobRubric(BaseModel):
    jd_id: str
    version: str = "v1"
    status: Literal["DRAFT", "APPROVED"] = "DRAFT"
    created_at: str = Field(default_factory=_now_iso)
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    criteria: List[RubricCriterion] = Field(..., min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_weights(self) -> "JobRubric":
        if self.criteria:
            total_weight = sum(c.weight for c in self.criteria)
            # Normalize weights if they deviate slightly from 1.0
            if total_weight > 0 and abs(total_weight - 1.0) > 0.01:
                for c in self.criteria:
                    c.weight = round(c.weight / total_weight, 3)
        return self


# ── Evaluation Schemas (4b) ──────────────────────────────────────────────────

class CriterionEvidence(BaseModel):
    quote: str = Field(..., description="Verbatim text copied directly from the candidate resume")
    section: str = Field("General", description="Resume section header e.g. Experience, Projects, Skills")


class CriterionEvaluation(BaseModel):
    criterion_id: str
    status: Literal["met", "partial", "not_evidenced"] = Field(
        ...,
        description="'met' if strongly evidenced by quotes, 'partial' if partially evidenced, 'not_evidenced' if no quote found"
    )
    evidence: List[CriterionEvidence] = Field(default_factory=list)
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Model confidence score")

    @model_validator(mode="after")
    def validate_quotes_required_for_met(self) -> "CriterionEvaluation":
        if self.status in ("met", "partial") and not self.evidence:
            # If no quotes exist, strictly downgrade to not_evidenced
            self.status = "not_evidenced"
        return self


class ResumeEvaluation(BaseModel):
    parse_quality: Literal["good", "poor"] = Field(
        "good",
        description="'good' for normal text, 'poor' if text appears severely garbled, incomplete, or corrupted"
    )
    evaluations: List[CriterionEvaluation] = Field(..., min_length=1)
    verification_flags: List[str] = Field(default_factory=list)


# ── Reconciler & Decision Schemas (4d) ───────────────────────────────────────

class ReconciliationDecision(BaseModel):
    decision: Literal["AUTO", "HUMAN_REVIEW"]
    reason: str
    flag_notes: List[str] = Field(default_factory=list)
    weighted_score: float = 0.0
    must_haves_total: int = 0
    must_haves_met: int = 0


# ── Output Generators (4e) ───────────────────────────────────────────────────

class HRReport(BaseModel):
    candidate_id: str
    application_id: Optional[str] = None
    candidate_name: Optional[str] = None
    job_id: str
    rerank_rank: Optional[int] = None
    rerank_score: Optional[float] = None
    match_matrix: List[Dict[str, Any]]
    strengths: List[str]
    gaps: List[str]
    risks: List[str]
    interview_questions: List[str]
    generated_at: str = Field(default_factory=_now_iso)


class CandidateFeedback(BaseModel):
    resume_id: str
    job_id: str
    what_resume_showed: str
    gaps: List[str] = Field(..., min_length=1, max_length=4)
    actionable_suggestion: str
    generated_at: str = Field(default_factory=_now_iso)


# ── Review Queue Schema (4g) ────────────────────────────────────────────────

class ReviewQueueItem(BaseModel):
    resume_id: str
    candidate_id: str
    job_id: str
    tenant_id: Optional[str] = None
    status: Literal["NEEDS_REVIEW", "PROMOTED", "CONFIRMED_REJECT", "RUBRIC_FIX"] = "NEEDS_REVIEW"
    flag_reasons: List[str]
    rerank_rank: Optional[int] = None
    weighted_score: float = 0.0
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    override_notes: Optional[str] = None
