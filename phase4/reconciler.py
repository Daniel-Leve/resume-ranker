"""
Phase 4d: Decision Reconciler.
Combines Phase 3 rerank ranking with Phase 4 blind rubric evaluation to detect false negatives,
weak evidence candidates, and route quality flags to the Human Review Queue.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from phase4 import config
from phase4.schemas import (
    JobRubric,
    ReconciliationDecision,
    ResumeEvaluation,
)

logger = logging.getLogger(__name__)


def reconcile_decision(
    candidate_id: str,
    is_shortlisted: bool,
    evaluation: ResumeEvaluation,
    rubric: JobRubric,
    rerank_rank: Optional[int] = None,
    confidence_threshold: float = config.CONFIDENCE_THRESHOLD,
) -> ReconciliationDecision:
    """
    Reconcile the Phase 3 rerank decision with Phase 4 rubric results.

    Rules:
    - both agree -> AUTO
    - rerank=reject but all must-haves met -> HUMAN_REVIEW ("possible false negative")
    - rerank=shortlist but must-haves missing -> keep shortlisted with "high similarity, weak evidence" note
    - parse_quality=poor, low confidence, or verification flags -> HUMAN_REVIEW
    """
    must_criteria = [c for c in rubric.criteria if c.type == "must"]
    nice_criteria = [c for c in rubric.criteria if c.type == "nice"]

    eval_by_id = {e.criterion_id: e for e in evaluation.evaluations}

    # Count must-haves
    must_total = len(must_criteria)
    must_met = sum(
        1 for c in must_criteria
        if eval_by_id.get(c.id) and eval_by_id[c.id].status == "met"
    )
    must_partial = sum(
        1 for c in must_criteria
        if eval_by_id.get(c.id) and eval_by_id[c.id].status == "partial"
    )

    all_must_haves_met = (must_met == must_total and must_total > 0)

    # Calculate weighted score across all criteria
    weighted_score = 0.0
    for c in rubric.criteria:
        e = eval_by_id.get(c.id)
        if e:
            if e.status == "met":
                weighted_score += c.weight * 1.0
            elif e.status == "partial":
                weighted_score += c.weight * 0.5

    flag_notes: List[str] = list(evaluation.verification_flags)
    requires_human_review = False
    reasons: List[str] = []

    # 1. Quality & Confidence Checks
    if evaluation.parse_quality == "poor":
        requires_human_review = True
        flag_notes.append("poor_parse_quality: text appears truncated or unreadable")
        reasons.append("Resume parse quality is poor.")

    min_confidence = min((e.confidence for e in evaluation.evaluations), default=1.0)
    if min_confidence < confidence_threshold:
        requires_human_review = True
        flag_notes.append(f"low_confidence: min confidence {min_confidence:.2f} < {confidence_threshold}")
        reasons.append("Model confidence is below threshold.")

    if any("unverified_quote" in f for f in evaluation.verification_flags):
        requires_human_review = True
        reasons.append("Evidence quote failed verification against raw resume text.")

    # 2. Ranking vs Rubric Alignment Checks
    if not is_shortlisted and all_must_haves_met:
        # Candidate rejected by reranker but satisfies all must-haves!
        requires_human_review = True
        flag_notes.append("possible_false_negative: rejected by rerank but all must-have criteria are met")
        reasons.append("Possible false negative: rejected candidate satisfies all must-have criteria.")

    elif is_shortlisted and not all_must_haves_met:
        # Candidate shortlisted by reranker but missing some must-haves!
        requires_human_review = True
        flag_notes.append("high_similarity_weak_evidence: candidate shortlisted but has missing/partial must-haves")
        reasons.append("High search similarity, but candidate failed one or more must-have criteria.")

    # 3. Final Decision Synthesis
    if requires_human_review:
        decision = "HUMAN_REVIEW"
        reason = "; ".join(reasons) if reasons else "Flagged for manual review."
    else:
        decision = "AUTO"
        if is_shortlisted:
            reason = "Auto-approved: Shortlist confirmed by rubric evaluation."
        else:
            reason = "Auto-approved: Rejection confirmed by rubric gaps."

    return ReconciliationDecision(
        decision=decision,
        reason=reason,
        flag_notes=flag_notes,
        weighted_score=round(weighted_score, 3),
        must_haves_total=must_total,
        must_haves_met=must_met,
    )
