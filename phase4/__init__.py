"""
Phase 4: Faithful Explainability Layer for AI Resume Screening SaaS.
"""
from phase4.daily_budget import DailyBudget
from phase4.evaluator import evaluate_resume_blind
from phase4.evidence_verifier import verify_resume_evaluation
from phase4.generators import generate_candidate_feedback, generate_hr_report
from phase4.llm_client import GroqClient, LLMClient, MockLLMClient
from phase4.orchestrator import Phase4Orchestrator
from phase4.privacy import PIIRedactor
from phase4.rate_limiter import RateLimiter
from phase4.reconciler import reconcile_decision
from phase4.review_queue import ReviewQueueManager
from phase4.rubric_builder import approve_rubric, build_rubric, get_rubric
from phase4.schemas import (
    CandidateFeedback,
    HRReport,
    JobRubric,
    ReconciliationDecision,
    ResumeEvaluation,
    ReviewQueueItem,
    RubricCriterion,
)

__version__ = "2.0.0"

__all__ = [
    "DailyBudget",
    "evaluate_resume_blind",
    "verify_resume_evaluation",
    "generate_candidate_feedback",
    "generate_hr_report",
    "GroqClient",
    "LLMClient",
    "MockLLMClient",
    "Phase4Orchestrator",
    "PIIRedactor",
    "RateLimiter",
    "reconcile_decision",
    "ReviewQueueManager",
    "approve_rubric",
    "build_rubric",
    "get_rubric",
    "CandidateFeedback",
    "HRReport",
    "JobRubric",
    "ReconciliationDecision",
    "ResumeEvaluation",
    "ReviewQueueItem",
    "RubricCriterion",
]
