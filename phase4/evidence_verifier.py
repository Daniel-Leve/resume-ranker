"""
Phase 4c: Pure-Code Evidence Verifier (NO LLM).
Verifies that all extracted quotes exist verbatim in the candidate resume using fuzzy matching.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from phase4 import config
from phase4.schemas import CriterionEvaluation, ResumeEvaluation

logger = logging.getLogger(__name__)

# Check for rapidfuzz or fallback to difflib
try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    _HAS_RAPIDFUZZ = False


def _normalize(text: str) -> str:
    """Normalize text by lowercasing and collapsing whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def match_quote_in_text(
    quote: str,
    text: str,
    threshold: float = config.EVIDENCE_FUZZY_THRESHOLD,
) -> Tuple[bool, float]:
    """
    Check if a quote exists in the source text using fuzzy substring matching.
    Returns (is_match, similarity_score).
    """
    quote_norm = _normalize(quote)
    text_norm = _normalize(text)

    if not quote_norm:
        return False, 0.0

    # 1. Exact match fast path
    if quote_norm in text_norm:
        return True, 100.0

    # 2. Fuzzy partial matching
    if _HAS_RAPIDFUZZ:
        score = float(fuzz.partial_ratio(quote_norm, text_norm))
        return score >= threshold, score
    else:
        # Standard library difflib fallback
        matcher = difflib.SequenceMatcher(None, quote_norm, text_norm)
        match = matcher.find_longest_match(0, len(quote_norm), 0, len(text_norm))
        longest_sub_len = match.size
        score = (longest_sub_len / max(1, len(quote_norm))) * 100.0
        return score >= threshold, score


class VerificationMetrics:
    """Tracks quote verification statistics across batch runs."""

    def __init__(self) -> None:
        self.total_quotes_checked: int = 0
        self.quotes_passed: int = 0
        self.quotes_failed: int = 0

    def record(self, passed: bool) -> None:
        self.total_quotes_checked += 1
        if passed:
            self.quotes_passed += 1
        else:
            self.quotes_failed += 1

    @property
    def failure_rate(self) -> float:
        if self.total_quotes_checked == 0:
            return 0.0
        return round((self.quotes_failed / self.total_quotes_checked) * 100.0, 2)

    def summary(self) -> str:
        return (
            f"Checked: {self.total_quotes_checked} | "
            f"Passed: {self.quotes_passed} | "
            f"Failed: {self.quotes_failed} ({self.failure_rate}%)"
        )


GLOBAL_VERIFICATION_METRICS = VerificationMetrics()


def verify_resume_evaluation(
    evaluation: ResumeEvaluation,
    raw_resume_text: str,
    threshold: float = config.EVIDENCE_FUZZY_THRESHOLD,
    metrics: Optional[VerificationMetrics] = None,
) -> Tuple[ResumeEvaluation, bool, List[str]]:
    """
    Verify all evidence quotes against the raw resume text.

    Returns:
        (updated_evaluation, all_quotes_valid, list_of_failed_quotes)
    """
    m = metrics or GLOBAL_VERIFICATION_METRICS
    failed_quotes: List[str] = []
    updated_evaluations: List[CriterionEvaluation] = []
    flags = list(evaluation.verification_flags)

    for crit_eval in evaluation.evaluations:
        valid_evidence = []
        criterion_had_failures = False

        for ev in crit_eval.evidence:
            is_valid, score = match_quote_in_text(ev.quote, raw_resume_text, threshold=threshold)
            m.record(is_valid)

            if is_valid:
                valid_evidence.append(ev)
            else:
                criterion_had_failures = True
                failed_quotes.append(f"[{crit_eval.criterion_id}] '{ev.quote}' (score={score:.1f})")
                logger.warning(
                    "Quote verification failed for criterion %s: '%s' (fuzzy score: %.1f < %.1f)",
                    crit_eval.criterion_id, ev.quote[:60], score, threshold
                )

        # If any quotes failed and no valid quotes remain, downgrade to not_evidenced
        if criterion_had_failures and not valid_evidence:
            updated_eval = CriterionEvaluation(
                criterion_id=crit_eval.criterion_id,
                status="not_evidenced",
                evidence=[],
                confidence=min(crit_eval.confidence, 0.40),
            )
            flags.append(f"downgraded_{crit_eval.criterion_id}_unverified_quote")
        else:
            updated_eval = CriterionEvaluation(
                criterion_id=crit_eval.criterion_id,
                status=crit_eval.status,
                evidence=valid_evidence,
                confidence=crit_eval.confidence,
            )

        updated_evaluations.append(updated_eval)

    all_valid = len(failed_quotes) == 0
    updated_obj = ResumeEvaluation(
        parse_quality=evaluation.parse_quality,
        evaluations=updated_evaluations,
        verification_flags=flags,
    )

    return updated_obj, all_valid, failed_quotes
