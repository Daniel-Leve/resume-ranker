"""
Phase 4b: Blind Resume Evaluator.
Evaluates resume text against an approved JD Rubric with verbatim quote extraction.
Completely blind to Phase 2/3 ranking and scores.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from pydantic import ValidationError

from phase4.llm_client import LLMClient, LLMResponse
from phase4.schemas import (
    CriterionEvaluation,
    CriterionEvidence,
    JobRubric,
    ResumeEvaluation,
)

logger = logging.getLogger(__name__)

EVALUATOR_SYSTEM_PROMPT = """You are a rigorous, objective, and evidence-grounded candidate evaluation system.
Your job is to evaluate a candidate resume strictly against the provided job rubric.

CORE RULES (STRICT FAITHFULNESS):
1. BLIND EVALUATION: You are evaluating the resume solely on its factual contents against the rubric criteria.
2. VERBATIM QUOTES: Every claim of evidence must contain direct, verbatim quotes copied word-for-word from the resume text. Do NOT paraphrase or invent quotes.
3. STATUS VALUES:
   - "met": The resume provides clear, direct, and explicit quoted evidence satisfying the criterion. (REQUIRES AT LEAST ONE VERBATIM QUOTE).
   - "partial": The resume shows related, foundational, or partial experience, but lacks full scope or depth. (REQUIRES AT LEAST ONE VERBATIM QUOTE).
   - "not_evidenced": The resume does NOT provide direct textual evidence for this criterion. Use "not_evidenced", never "missing", because the candidate may have this skill outside what was written. If there is no verbatim quote, you MUST mark "not_evidenced".
4. PARSE QUALITY:
   - "good": Text is legible and coherent.
   - "poor": Text appears heavily scrambled, truncated, corrupted, or unreadable OCR output.
5. SINGLE-CALL EFFICIENCY: Evaluate ALL rubric criteria in this single response.

OUTPUT FORMAT:
Respond with strictly valid JSON matching this schema:
{
  "parse_quality": "good",
  "evaluations": [
    {
      "criterion_id": "c1",
      "status": "met",
      "evidence": [
        {
          "quote": "Led development of core billing microservices using Python 3.11 and FastAPI",
          "section": "Experience"
        }
      ],
      "confidence": 0.95
    }
  ]
}
"""


def evaluate_resume_blind(
    redacted_resume_text: str,
    rubric: JobRubric,
    llm_client: LLMClient,
    candidate_id: str = "unknown",
) -> Tuple[ResumeEvaluation, LLMResponse]:
    """
    Evaluate candidate resume against all criteria in the rubric in a single compact call.
    Guaranteed blind to ranking. Validates output with Pydantic.
    """
    if rubric.status != "APPROVED":
        raise ValueError(
            f"Rubric {rubric.jd_id} is in status '{rubric.status}'. Resumes can ONLY be evaluated against an APPROVED rubric."
        )

    # Format criteria list compactly
    criteria_lines = []
    for c in rubric.criteria:
        criteria_lines.append(
            f"- [{c.id}] ({c.type.upper()}, weight={c.weight}): {c.description}\n  How to verify: {c.how_to_verify}"
        )
    criteria_block = "\n".join(criteria_lines)

    user_prompt = f"""EVALUATE THIS RESUME AGAINST THE APPROVED RUBRIC.

=== APPROVED RUBRIC ({rubric.jd_id} v{rubric.version}) ===
{criteria_block}

=== CANDIDATE RESUME TEXT ===
{redacted_resume_text}
"""

    messages = [
        {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        evaluation, resp = llm_client.complete_structured(
            messages=messages,
            schema_class=ResumeEvaluation,
            temperature=0.0,
        )
        return evaluation, resp

    except (json.JSONDecodeError, ValidationError) as err:
        logger.error(
            "Evaluation schema validation failed for candidate %s after retry: %s. Marking as poor parse / needs review.",
            candidate_id, err
        )
        # Create a fallback evaluation flagging needs review
        fallback_evals = [
            CriterionEvaluation(
                criterion_id=c.id,
                status="not_evidenced",
                evidence=[],
                confidence=0.0,
            )
            for c in rubric.criteria
        ]
        fallback_obj = ResumeEvaluation(
            parse_quality="poor",
            evaluations=fallback_evals,
            verification_flags=[f"schema_validation_failed: {str(err)[:100]}"],
        )
        empty_resp = LLMResponse(content="{}", total_tokens=0, model="fallback")
        return fallback_obj, empty_resp
