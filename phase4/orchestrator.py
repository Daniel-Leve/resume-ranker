"""
Phase 4f: Resumable Explainability Orchestrator.
Coordinates Rubric, PII Redaction, Rate Limiting, Budget Caps, Blind Evaluation,
Quote Verification, Decision Reconciliation, Output Generation, and Review Queue.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from phase4 import config
from phase4.daily_budget import DailyBudget, compute_resume_hash
from phase4.evaluator import evaluate_resume_blind
from phase4.evidence_verifier import (
    GLOBAL_VERIFICATION_METRICS,
    VerificationMetrics,
    verify_resume_evaluation,
)
from phase4.generators import generate_candidate_feedback, generate_hr_report
from phase4.llm_client import GroqClient, LLMClient
from phase4.privacy import PIIRedactor
from phase4.rate_limiter import RateLimiter
from phase4.reconciler import reconcile_decision
from phase4.review_queue import GLOBAL_REVIEW_QUEUE, ReviewQueueManager
from phase4.rubric_builder import get_rubric
from phase4.schemas import (
    CandidateFeedback,
    HRReport,
    JobRubric,
    ReconciliationDecision,
    ResumeEvaluation,
)

logger = logging.getLogger(__name__)


def _format_evidence_quote(m: Dict[str, Any]) -> str:
    quotes = m.get("quotes") or []
    if quotes and len(quotes) > 0 and quotes[0] and quotes[0].strip():
        return quotes[0].strip()
    status = m.get("status")
    if status == "met":
        return "Verified in resume text"
    elif status == "partial":
        return "Partially evidenced in resume"
    return "Not evidenced in resume"


class Phase4Orchestrator:
    """
    Coordinates end-to-end Phase 4 Explainability pipeline.
    Resumable, budget-safe, and privacy-preserving.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
        daily_budget: Optional[DailyBudget] = None,
        review_queue: Optional[ReviewQueueManager] = None,
        redactor: Optional[PIIRedactor] = None,
    ) -> None:
        self.llm_client = llm_client or GroqClient()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.daily_budget = daily_budget or DailyBudget()
        self.review_queue = review_queue or GLOBAL_REVIEW_QUEUE
        self.redactor = redactor or PIIRedactor()
        self.metrics = GLOBAL_VERIFICATION_METRICS

    def evaluate_batch(
        self,
        jd_id: str,
        resumes: List[Dict[str, Any]],
        phase3_results: Optional[Dict[str, Any]] = None,
        rubric: Optional[JobRubric] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a batch of resumes against the approved rubric.

        Args:
            jd_id: Job identifier.
            resumes: List of dicts with {"resume_id": str, "raw_text": str, "candidate_name": Optional[str]}.
            phase3_results: Optional Phase 3 rerank output containing shortlisted candidate IDs and ranks.
            rubric: Optional pre-loaded JobRubric. If None, loaded from disk.
            tenant_id: Optional tenant identifier for multitenant isolation.

        Returns:
            Dictionary with batch execution status, counts by state, and results.
        """
        # 1. Rubric Verification
        active_rubric = rubric or get_rubric(jd_id)
        if not active_rubric:
            raise FileNotFoundError(f"Rubric not found for job {jd_id}. Run build-rubric first.")
        if active_rubric.status != "APPROVED":
            raise ValueError(
                f"Rubric for {jd_id} is in status '{active_rubric.status}'. Explicit human approval is required before running evaluation."
            )

        # Build lookup for Phase 3 ranking
        shortlisted_candidates = set()
        ranks_by_cand = {}
        scores_by_cand = {}
        if phase3_results and "candidates" in phase3_results:
            for c in phase3_results["candidates"]:
                cid = c.get("candidate_id") or c.get("application_id")
                if cid:
                    shortlisted_candidates.add(cid)
                    ranks_by_cand[cid] = c.get("rerank_rank")
                    scores_by_cand[cid] = c.get("rerank_score")

        evaluated_count = 0
        pending_count = 0
        auto_count = 0
        human_review_count = 0
        cache_hits = 0

        hr_reports: List[HRReport] = []
        feedbacks: List[CandidateFeedback] = []
        review_items: List[Dict[str, Any]] = []

        candidate_results: Dict[str, Any] = {}

        total_resumes = len(resumes)
        logger.info("Starting Phase 4 evaluation for job %s (%d resumes)...", jd_id, total_resumes)

        for idx, resume_item in enumerate(resumes):
            resume_id = resume_item.get("resume_id") or f"resume_{idx+1}"
            raw_text = resume_item.get("raw_text") or resume_item.get("text") or ""
            cand_name = resume_item.get("candidate_name")
            app_id = resume_item.get("application_id")

            if not raw_text.strip():
                logger.warning("Empty text for resume %s — skipping.", resume_id)
                continue

            # 2. Check Daily Budget Before Processing
            if self.daily_budget.is_budget_exceeded():
                logger.warning(
                    "Daily token/request budget cap reached (>= 90%%). Pausing gracefully. Remaining %d resumes marked PENDING.",
                    total_resumes - idx
                )
                pending_count = total_resumes - idx
                break

            resume_hash = compute_resume_hash(raw_text)

            # 3. Check Resumable Cache
            cached_entry = self.daily_budget.get_cached_evaluation(
                jd_id=jd_id,
                resume_hash=resume_hash,
                rubric_version=active_rubric.version,
            )

            evaluation_obj: Optional[ResumeEvaluation] = None

            if cached_entry:
                cache_hits += 1
                logger.info("Resuming %s from cache (hash=%s).", resume_id, resume_hash[:8])
                evaluation_obj = ResumeEvaluation.model_validate(cached_entry["evaluation"])
            else:
                # 4. Redact PII
                redaction = self.redactor.redact(
                    text=raw_text,
                    candidate_id=resume_id,
                    candidate_name=cand_name,
                )

                # 5. Rate Limiter (sliding window pre-acquire)
                est_tokens = len(redaction.redacted_text) // 4 + 500
                self.rate_limiter.acquire(estimated_tokens=est_tokens)

                # 6. Blind Evaluation
                eval_raw, llm_resp = evaluate_resume_blind(
                    redacted_resume_text=redaction.redacted_text,
                    rubric=active_rubric,
                    llm_client=self.llm_client,
                    candidate_id=resume_id,
                )

                # Update RateLimiter & DailyBudget with actual usage
                self.rate_limiter.update_actual_usage(
                    estimated_tokens=est_tokens,
                    actual_tokens=llm_resp.total_tokens,
                )
                self.daily_budget.record_usage(
                    prompt_tokens=llm_resp.prompt_tokens,
                    completion_tokens=llm_resp.completion_tokens,
                    total_tokens=llm_resp.total_tokens,
                )

                # 7. Evidence Quote Verification (Pure Code)
                verified_eval, all_passed, failed_quotes = verify_resume_evaluation(
                    evaluation=eval_raw,
                    raw_resume_text=raw_text,
                    metrics=self.metrics,
                )

                # If quotes failed, retry evaluation once
                if not all_passed:
                    logger.info("Quote verification failed for %s. Retrying evaluation once...", resume_id)
                    retry_eval, retry_resp = evaluate_resume_blind(
                        redacted_resume_text=redaction.redacted_text,
                        rubric=active_rubric,
                        llm_client=self.llm_client,
                        candidate_id=resume_id,
                    )
                    self.daily_budget.record_usage(
                        prompt_tokens=retry_resp.prompt_tokens,
                        completion_tokens=retry_resp.completion_tokens,
                        total_tokens=retry_resp.total_tokens,
                    )
                    verified_eval, all_passed_retry, failed_retry = verify_resume_evaluation(
                        evaluation=retry_eval,
                        raw_resume_text=raw_text,
                        metrics=self.metrics,
                    )
                    if not all_passed_retry:
                        verified_eval.verification_flags.append("persistent_unverified_quote")

                evaluation_obj = verified_eval

                # Save to cache
                self.daily_budget.save_cached_evaluation(
                    jd_id=jd_id,
                    resume_hash=resume_hash,
                    rubric_version=active_rubric.version,
                    resume_id=resume_id,
                    evaluation_data=evaluation_obj.model_dump(),
                )

            evaluated_count += 1

            # 8. Reconcile with Phase 3 Rerank Decision
            is_shortlisted = resume_id in shortlisted_candidates
            recon = reconcile_decision(
                candidate_id=resume_id,
                is_shortlisted=is_shortlisted,
                evaluation=evaluation_obj,
                rubric=active_rubric,
                rerank_rank=ranks_by_cand.get(resume_id),
            )

            # 9. Route to Review Queue or Generate Final Outputs
            if recon.decision == "HUMAN_REVIEW":
                human_review_count += 1
                q_item = self.review_queue.enqueue(
                    resume_id=resume_id,
                    candidate_id=resume_id,
                    job_id=jd_id,
                    tenant_id=tenant_id,
                    flag_reasons=recon.flag_notes,
                    rerank_rank=ranks_by_cand.get(resume_id),
                    weighted_score=recon.weighted_score,
                    payload={
                        "evaluation": evaluation_obj.model_dump(),
                        "reconciliation": recon.model_dump(),
                        "is_shortlisted": is_shortlisted,
                        "candidate_name": cand_name,
                        "application_id": app_id,
                    },
                )
                review_items.append(q_item.model_dump())

                # Generate HR report for review candidate so recruiter can inspect match matrix & criteria
                rep = generate_hr_report(
                    candidate_id=resume_id,
                    job_id=jd_id,
                    evaluation=evaluation_obj,
                    rubric=active_rubric,
                    reconciliation=recon,
                    candidate_name=cand_name,
                    application_id=app_id,
                    rerank_rank=ranks_by_cand.get(resume_id),
                    rerank_score=scores_by_cand.get(resume_id),
                )
                hr_reports.append(rep)
                rep_dict = rep.model_dump()
                rep_dict["final_score"] = round(recon.weighted_score * 100, 1)
                rep_dict["decision"] = "UNDECIDED"
                rep_dict["rubric_version"] = active_rubric.version
                rep_dict["criteria_scores"] = [
                    {
                        "criterion_name": m.get("description", m.get("criterion_id")),
                        "score": 5 if m.get("status") == "met" else (3 if m.get("status") == "partial" else 1),
                        "evidence_quote": _format_evidence_quote(m),
                    }
                    for m in rep_dict.get("match_matrix", [])
                ]

                candidate_results[resume_id] = {
                    "candidate_id": resume_id,
                    "application_id": app_id,
                    "decision": "UNDECIDED",
                    "review_status": "HUMAN_REVIEW",
                    "weighted_score": recon.weighted_score,
                    "reconciliation": recon.model_dump(),
                    "review_queue_item": q_item.model_dump(),
                    "hr_report": rep_dict,
                }
            else:
                auto_count += 1
                if is_shortlisted:
                    rep = generate_hr_report(
                        candidate_id=resume_id,
                        job_id=jd_id,
                        evaluation=evaluation_obj,
                        rubric=active_rubric,
                        reconciliation=recon,
                        candidate_name=cand_name,
                        application_id=app_id,
                        rerank_rank=ranks_by_cand.get(resume_id),
                        rerank_score=scores_by_cand.get(resume_id),
                    )
                    hr_reports.append(rep)
                    rep_dict = rep.model_dump()
                    rep_dict["final_score"] = round(recon.weighted_score * 100, 1)
                    rep_dict["decision"] = "SHORTLISTED"
                    rep_dict["rubric_version"] = active_rubric.version
                    rep_dict["criteria_scores"] = [
                        {
                            "criterion_name": m.get("description", m.get("criterion_id")),
                            "score": 5 if m.get("status") == "met" else (3 if m.get("status") == "partial" else 1),
                            "evidence_quote": _format_evidence_quote(m),
                        }
                        for m in rep_dict.get("match_matrix", [])
                    ]
                    candidate_results[resume_id] = {
                        "candidate_id": resume_id,
                        "application_id": app_id,
                        "decision": "SHORTLISTED",
                        "weighted_score": recon.weighted_score,
                        "reconciliation": recon.model_dump(),
                        "hr_report": rep_dict,
                    }
                else:
                    fb = generate_candidate_feedback(
                        resume_id=resume_id,
                        job_id=jd_id,
                        evaluation=evaluation_obj,
                        rubric=active_rubric,
                    )
                    feedbacks.append(fb)
                    candidate_results[resume_id] = {
                        "candidate_id": resume_id,
                        "application_id": app_id,
                        "decision": "REJECTED",
                        "weighted_score": recon.weighted_score,
                        "reconciliation": recon.model_dump(),
                        "feedback": fb.model_dump(),
                    }

        budget_status = self.daily_budget.get_budget_status()

        # Calculate estimated days remaining
        tokens_per_resume = 1800  # realistic average
        daily_capacity_resumes = max(1, config.RATE_LIMIT_TPD // tokens_per_resume)
        days_remaining = round(pending_count / daily_capacity_resumes, 1) if pending_count > 0 else 0.0

        return {
            "job_id": jd_id,
            "status": "COMPLETED" if pending_count == 0 else "PARTIALLY_PENDING",
            "total_submitted": total_resumes,
            "evaluated_count": evaluated_count,
            "pending_count": pending_count,
            "cache_hits": cache_hits,
            "auto_decisions": auto_count,
            "human_review_queue": human_review_count,
            "hr_reports_generated": len(hr_reports),
            "candidate_feedbacks_generated": len(feedbacks),
            "reports": [r.model_dump() for r in hr_reports],
            "feedbacks": [f.model_dump() for f in feedbacks],
            "candidate_results": candidate_results,
            "budget": budget_status,
            "estimated_days_remaining": days_remaining,
            "verification_metric": self.metrics.summary(),
        }
