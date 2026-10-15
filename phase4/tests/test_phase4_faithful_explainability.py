"""
Comprehensive Unit & Integration Test Suite for Phase 4: Faithful Explainability Layer.
Tests:
- PII Redactor (name, email, phone, address, gender, photo, DOB, URLs, mapping)
- LLM Client & MockLLMClient with structured validation
- RateLimiter sliding window
- DailyBudget JSON file persistence & Resumable Cache (Zero SQLite)
- Rubric Builder & Approval Gate
- Blind Resume Evaluator
- Pure-Code Evidence Verifier (rapidfuzz / difflib)
- Decision Reconciler (AUTO vs HUMAN_REVIEW rules)
- HR Report & Candidate Feedback Generators (no scores in feedback, 3-5 interview questions)
- Human Review Queue (promote, confirm_reject, fix_rubric)
- End-to-End Orchestrator Batch Pipeline
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from phase4.daily_budget import DailyBudget, compute_resume_hash
from phase4.evaluator import evaluate_resume_blind
from phase4.evidence_verifier import (
    VerificationMetrics,
    match_quote_in_text,
    verify_resume_evaluation,
)
from phase4.generators import generate_candidate_feedback, generate_hr_report
from phase4.llm_client import MockLLMClient
from phase4.orchestrator import Phase4Orchestrator
from phase4.privacy import PIIRedactor
from phase4.rate_limiter import RateLimiter
from phase4.reconciler import reconcile_decision
from phase4.review_queue import ReviewQueueManager
from phase4.rubric_builder import approve_rubric, build_rubric
from phase4.schemas import (
    CriterionEvaluation,
    CriterionEvidence,
    JobRubric,
    ResumeEvaluation,
    RubricCriterion,
)


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="phase4_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_rubric():
    return JobRubric(
        jd_id="backend-engineer-001",
        version="v1",
        status="APPROVED",
        criteria=[
            RubricCriterion(
                id="c1",
                description="3+ years of Python backend engineering with FastAPI or Django",
                type="must",
                weight=0.5,
                how_to_verify="Look for production Python frameworks and years of experience",
            ),
            RubricCriterion(
                id="c2",
                description="Hands-on experience with MongoDB or distributed databases",
                type="must",
                weight=0.3,
                how_to_verify="Look for database modeling, queries, or indexing in production",
            ),
            RubricCriterion(
                id="c3",
                description="Experience with AWS Lambda, SQS, or serverless architectures",
                type="nice",
                weight=0.2,
                how_to_verify="Look for AWS serverless tooling and cloud deployments",
            ),
        ],
    )


# ── 1. Privacy & PII Redaction ───────────────────────────────────────────────

class TestPrivacyAndPII:
    def test_redact_pii_entities(self):
        redactor = PIIRedactor(enabled=True)
        raw_resume = (
            "John Doe\n"
            "Email: john.doe@example.com | Phone: +1 (555) 234-5678\n"
            "LinkedIn: https://linkedin.com/in/johndoe | GitHub: https://github.com/johndoe\n"
            "Address: 742 Evergreen Terrace, Springfield\n"
            "DOB: 1990-05-15 | Gender: Male\n"
            "Photo attached: yes\n"
            "Experienced Python engineer who built backend APIs."
        )

        result = redactor.redact(
            text=raw_resume,
            candidate_id="cand-001",
            candidate_name="John Doe",
        )

        redacted = result.redacted_text
        assert "john.doe@example.com" not in redacted
        assert "[EMAIL_REDACTED]" in redacted
        assert "555" not in redacted
        assert "[PHONE_REDACTED]" in redacted
        assert "https://linkedin.com" not in redacted
        assert "[URL_REDACTED]" in redacted
        assert "1990-05-15" not in redacted
        assert "[DOB_REDACTED]" in redacted
        assert "Male" not in redacted
        assert "[GENDER_REDACTED]" in redacted
        assert "John Doe" not in redacted
        assert "[NAME_REDACTED]" in redacted

        # Check candidate pseudonym mapping
        assert result.masked_candidate_id == "cand_masked_0001"
        assert redactor.resolve_candidate_id("cand_masked_0001") == "cand-001"

    def test_redact_disabled_warning(self):
        redactor = PIIRedactor(enabled=False)
        result = redactor.redact("John Doe john@example.com", "cand-002")
        assert "john@example.com" in result.redacted_text


# ── 2. RateLimiter & DailyBudget (Zero SQLite) ────────────────────────────────

class TestRateLimiterAndDailyBudget:
    def test_rate_limiter_window(self):
        limiter = RateLimiter(max_rpm=5, max_tpm=1000, window_sec=60.0)
        waited = limiter.acquire(estimated_tokens=200)
        assert waited == 0.0
        limiter.update_actual_usage(estimated_tokens=200, actual_tokens=250)

        rpm, tpm = limiter.current_usage()
        assert rpm == 1
        assert tpm == 250

    def test_daily_budget_persistence_and_caps(self, temp_dir):
        budget_file = temp_dir / "budget.json"
        cache_dir = temp_dir / "cache"
        budget = DailyBudget(
            budget_file=budget_file,
            cache_dir=cache_dir,
            daily_token_limit=10000,
            daily_request_limit=100,
            stop_threshold=0.90,
        )

        # Initial state
        assert not budget.is_budget_exceeded()
        status = budget.get_budget_status()
        assert status["tokens_used_today"] == 0

        # Record usage below threshold
        budget.record_usage(prompt_tokens=4000, completion_tokens=4000)
        assert not budget.is_budget_exceeded()  # 8000 < 9000 (90%)

        # Record more usage exceeding 90% threshold
        budget.record_usage(prompt_tokens=1000, completion_tokens=500)
        assert budget.is_budget_exceeded()  # 9500 >= 9000

        # Verify persistence across instances
        budget2 = DailyBudget(budget_file=budget_file, cache_dir=cache_dir)
        usage = budget2.get_usage_today()
        assert usage["total_tokens"] == 9500

    def test_resumable_evaluation_cache(self, temp_dir):
        budget_file = temp_dir / "budget.json"
        cache_dir = temp_dir / "cache"
        budget = DailyBudget(budget_file=budget_file, cache_dir=cache_dir)

        resume_text = "Senior Python developer with AWS Lambda and DynamoDB experience."
        r_hash = compute_resume_hash(resume_text)

        # Miss
        cached = budget.get_cached_evaluation("job-1", r_hash, "v1")
        assert cached is None

        # Save
        data = {"parse_quality": "good", "evaluations": []}
        key = budget.save_cached_evaluation("job-1", r_hash, "v1", "cand-1", data)
        assert key is not None

        # Hit
        cached_hit = budget.get_cached_evaluation("job-1", r_hash, "v1")
        assert cached_hit is not None
        assert cached_hit["evaluation"]["parse_quality"] == "good"


# ── 3. Rubric Builder & Approval Gate ────────────────────────────────────────

class TestRubricBuilderAndGate:
    def test_build_and_approve_rubric(self, temp_dir):
        canned_llm = json.dumps({
            "criteria": [
                {
                    "id": "c1",
                    "description": "5+ years backend engineering in Python",
                    "type": "must",
                    "weight": 0.6,
                    "how_to_verify": "Look for 5+ years experience and senior titles",
                },
                {
                    "id": "c2",
                    "description": "Experience deploying on AWS ECS or Lambda",
                    "type": "nice",
                    "weight": 0.4,
                    "how_to_verify": "Look for cloud infrastructure keywords",
                },
            ]
        })
        mock_llm = MockLLMClient(canned_responses=[canned_llm])

        jd_text = "We are seeking a Senior Python Engineer with 5+ years experience building cloud services."
        rubric = build_rubric(
            jd_text=jd_text,
            jd_id="sr-py-01",
            llm_client=mock_llm,
            rubrics_dir=temp_dir,
            version="v1",
        )

        assert rubric.status == "DRAFT"
        assert len(rubric.criteria) == 2

        # Check refusal on draft rubric
        with pytest.raises(ValueError, match="is in status 'DRAFT'"):
            evaluate_resume_blind("some resume text", rubric, mock_llm)

        # Approve rubric
        approved = approve_rubric(jd_id="sr-py-01", rubrics_dir=temp_dir, version="v1")
        assert approved.status == "APPROVED"
        assert approved.approved_by == "recruiter"
        assert approved.approved_at is not None


# ── 4. Blind Evaluator & Evidence Verifier ───────────────────────────────────

class TestEvaluatorAndEvidenceVerifier:
    def test_blind_evaluation_success(self, sample_rubric):
        canned_eval = json.dumps({
            "parse_quality": "good",
            "evaluations": [
                {
                    "criterion_id": "c1",
                    "status": "met",
                    "evidence": [
                        {"quote": "4 years developing microservices in Python using FastAPI", "section": "Experience"}
                    ],
                    "confidence": 0.95,
                },
                {
                    "criterion_id": "c2",
                    "status": "met",
                    "evidence": [
                        {"quote": "Designed MongoDB document schemas for order processing", "section": "Experience"}
                    ],
                    "confidence": 0.90,
                },
                {
                    "criterion_id": "c3",
                    "status": "not_evidenced",
                    "evidence": [],
                    "confidence": 0.85,
                },
            ]
        })
        mock_llm = MockLLMClient(canned_responses=[canned_eval])

        resume_text = (
            "Experience:\n"
            "- 4 years developing microservices in Python using FastAPI.\n"
            "- Designed MongoDB document schemas for order processing."
        )

        eval_res, resp = evaluate_resume_blind(resume_text, sample_rubric, mock_llm)
        assert eval_res.parse_quality == "good"
        assert len(eval_res.evaluations) == 3
        assert eval_res.evaluations[0].status == "met"
        assert eval_res.evaluations[2].status == "not_evidenced"

        # Verify quotes against resume text
        metrics = VerificationMetrics()
        verified_eval, all_passed, failed = verify_resume_evaluation(
            evaluation=eval_res,
            raw_resume_text=resume_text,
            metrics=metrics,
        )
        assert all_passed
        assert len(failed) == 0
        assert metrics.failure_rate == 0.0

    def test_evidence_verifier_downgrade_on_hallucinated_quote(self, sample_rubric):
        fake_quote = "Built proprietary quantum cryptography framework in Rust"
        eval_with_fake = ResumeEvaluation(
            parse_quality="good",
            evaluations=[
                CriterionEvaluation(
                    criterion_id="c1",
                    status="met",
                    evidence=[CriterionEvidence(quote=fake_quote, section="Skills")],
                    confidence=0.90,
                )
            ]
        )
        real_resume = "Simple web developer with HTML, CSS and basic JavaScript experience."

        metrics = VerificationMetrics()
        verified, all_passed, failed = verify_resume_evaluation(
            evaluation=eval_with_fake,
            raw_resume_text=real_resume,
            metrics=metrics,
        )

        assert not all_passed
        assert len(failed) == 1
        assert verified.evaluations[0].status == "not_evidenced"
        assert any("downgraded_c1_unverified_quote" in f for f in verified.verification_flags)
        assert metrics.quotes_failed == 1


# ── 5. Reconciler Rules ──────────────────────────────────────────────────────

class TestDecisionReconciler:
    def test_both_agree_shortlist_auto(self, sample_rubric):
        evaluation = ResumeEvaluation(
            parse_quality="good",
            evaluations=[
                CriterionEvaluation(criterion_id="c1", status="met", evidence=[CriterionEvidence(quote="Python", section="Exp")]),
                CriterionEvaluation(criterion_id="c2", status="met", evidence=[CriterionEvidence(quote="MongoDB", section="Exp")]),
                CriterionEvaluation(criterion_id="c3", status="not_evidenced", evidence=[]),
            ]
        )
        decision = reconcile_decision("cand-1", is_shortlisted=True, evaluation=evaluation, rubric=sample_rubric, rerank_rank=1)
        assert decision.decision == "AUTO"
        assert decision.must_haves_met == 2
        assert decision.must_haves_total == 2

    def test_false_negative_routes_to_human_review(self, sample_rubric):
        # Candidate was rejected by reranker, but satisfies all must-haves!
        evaluation = ResumeEvaluation(
            parse_quality="good",
            evaluations=[
                CriterionEvaluation(criterion_id="c1", status="met", evidence=[CriterionEvidence(quote="Python", section="Exp")]),
                CriterionEvaluation(criterion_id="c2", status="met", evidence=[CriterionEvidence(quote="MongoDB", section="Exp")]),
                CriterionEvaluation(criterion_id="c3", status="not_evidenced", evidence=[]),
            ]
        )
        decision = reconcile_decision("cand-reject", is_shortlisted=False, evaluation=evaluation, rubric=sample_rubric, rerank_rank=15)
        assert decision.decision == "HUMAN_REVIEW"
        assert any("possible_false_negative" in f for f in decision.flag_notes)

    def test_high_similarity_weak_evidence_reconciliation(self, sample_rubric):
        # Candidate was shortlisted by reranker, but missing a must-have!
        evaluation = ResumeEvaluation(
            parse_quality="good",
            evaluations=[
                CriterionEvaluation(criterion_id="c1", status="met", evidence=[CriterionEvidence(quote="Python", section="Exp")]),
                CriterionEvaluation(criterion_id="c2", status="not_evidenced", evidence=[]),  # missing must-have
                CriterionEvaluation(criterion_id="c3", status="met", evidence=[CriterionEvidence(quote="AWS", section="Exp")]),
            ]
        )
        decision = reconcile_decision("cand-short", is_shortlisted=True, evaluation=evaluation, rubric=sample_rubric, rerank_rank=2)
        # Keeps shortlisted (AUTO), but attaches flag note
        assert decision.decision == "AUTO"
        assert any("high_similarity_weak_evidence" in f for f in decision.flag_notes)

    def test_poor_parse_quality_routes_to_human_review(self, sample_rubric):
        evaluation = ResumeEvaluation(
            parse_quality="poor",
            evaluations=[
                CriterionEvaluation(criterion_id="c1", status="not_evidenced", evidence=[]),
                CriterionEvaluation(criterion_id="c2", status="not_evidenced", evidence=[]),
                CriterionEvaluation(criterion_id="c3", status="not_evidenced", evidence=[]),
            ]
        )
        decision = reconcile_decision("cand-corrupt", is_shortlisted=False, evaluation=evaluation, rubric=sample_rubric)
        assert decision.decision == "HUMAN_REVIEW"
        assert any("poor_parse_quality" in f for f in decision.flag_notes)


# ── 6. Output Generators ─────────────────────────────────────────────────────

class TestOutputGenerators:
    def test_generate_hr_report_shortlisted(self, sample_rubric, temp_dir):
        eval_obj = ResumeEvaluation(
            parse_quality="good",
            evaluations=[
                CriterionEvaluation(criterion_id="c1", status="met", evidence=[CriterionEvidence(quote="Python 3.11 lead", section="Experience")]),
                CriterionEvaluation(criterion_id="c2", status="partial", evidence=[CriterionEvidence(quote="Basic Mongo queries", section="Skills")]),
                CriterionEvaluation(criterion_id="c3", status="not_evidenced", evidence=[]),
            ]
        )
        report = generate_hr_report(
            candidate_id="cand-good",
            job_id="backend-01",
            evaluation=eval_obj,
            rubric=sample_rubric,
            candidate_name="Alice Smith",
            rerank_rank=1,
            rerank_score=0.96,
            reports_dir=temp_dir,
        )

        assert report.candidate_id == "cand-good"
        assert report.candidate_name == "Alice Smith"
        assert len(report.match_matrix) == 3
        assert len(report.strengths) >= 1
        assert len(report.gaps) >= 1
        # Exactly 3 to 5 interview questions
        assert 3 <= len(report.interview_questions) <= 5

        # Check saved files
        assert (temp_dir / "backend-01" / "hr_report_cand-good.json").exists()
        assert (temp_dir / "backend-01" / "hr_report_cand-good.md").exists()

    def test_generate_candidate_feedback_rejected(self, sample_rubric, temp_dir):
        eval_obj = ResumeEvaluation(
            parse_quality="good",
            evaluations=[
                CriterionEvaluation(criterion_id="c1", status="met", evidence=[CriterionEvidence(quote="Python junior", section="Experience")]),
                CriterionEvaluation(criterion_id="c2", status="not_evidenced", evidence=[]),
                CriterionEvaluation(criterion_id="c3", status="not_evidenced", evidence=[]),
            ]
        )
        fb = generate_candidate_feedback(
            resume_id="cand-rej-01",
            job_id="backend-01",
            evaluation=eval_obj,
            rubric=sample_rubric,
            feedback_dir=temp_dir,
        )

        assert fb.resume_id == "cand-rej-01"
        assert len(fb.gaps) >= 1
        assert "Python" in fb.what_resume_showed
        assert fb.actionable_suggestion is not None

        # Verify candidate feedback file was created and contains NO scores or ranks
        fb_file = temp_dir / "cand-rej-01.md"
        assert fb_file.exists()
        content = fb_file.read_text(encoding="utf-8")
        assert "score" not in content.lower()
        assert "rank" not in content.lower()
        assert "weight" not in content.lower()
        assert "percentile" not in content.lower()


# ── 7. Review Queue (Zero SQLite) ────────────────────────────────────────────

class TestReviewQueue:
    def test_enqueue_and_resolve_actions(self, temp_dir):
        q_file = temp_dir / "queue.json"
        h_file = temp_dir / "history.json"
        manager = ReviewQueueManager(queue_file=q_file, history_file=h_file)

        item = manager.enqueue(
            resume_id="res-101",
            candidate_id="cand-101",
            job_id="job-42",
            flag_reasons=["possible_false_negative"],
            rerank_rank=12,
            weighted_score=0.85,
        )
        assert item.status == "NEEDS_REVIEW"

        items = manager.list_items(job_id="job-42")
        assert len(items) == 1

        # Resolve with promote
        resolved = manager.resolve("res-101", action="promote", notes="Strong open-source background", resolved_by="recruiter-bob")
        assert resolved.status == "PROMOTED"
        assert resolved.resolved_by == "recruiter-bob"

        # Active queue is now empty
        assert len(manager.list_items(job_id="job-42")) == 0

        # Saved to history file
        assert h_file.exists()
        with open(h_file, "r", encoding="utf-8") as f:
            history = json.load(f)
        assert len(history) == 1
        assert history[0]["status"] == "PROMOTED"


# ── 8. End-to-End Orchestrator Batch Pipeline ────────────────────────────────

class TestOrchestratorBatch:
    def test_full_batch_run(self, sample_rubric, temp_dir):
        canned_resps = [
            # Resume 1: Shortlisted candidate
            json.dumps({
                "parse_quality": "good",
                "evaluations": [
                    {"criterion_id": "c1", "status": "met", "evidence": [{"quote": "5 years Python lead", "section": "Exp"}], "confidence": 0.95},
                    {"criterion_id": "c2", "status": "met", "evidence": [{"quote": "Engineered MongoDB clusters", "section": "Exp"}], "confidence": 0.90},
                    {"criterion_id": "c3", "status": "met", "evidence": [{"quote": "Deployed with AWS Lambda", "section": "Exp"}], "confidence": 0.85},
                ]
            }),
            # Resume 2: Rejected candidate
            json.dumps({
                "parse_quality": "good",
                "evaluations": [
                    {"criterion_id": "c1", "status": "not_evidenced", "evidence": [], "confidence": 0.80},
                    {"criterion_id": "c2", "status": "not_evidenced", "evidence": [], "confidence": 0.80},
                    {"criterion_id": "c3", "status": "not_evidenced", "evidence": [], "confidence": 0.80},
                ]
            }),
        ]
        mock_llm = MockLLMClient(canned_responses=canned_resps)

        b_file = temp_dir / "budget.json"
        c_dir = temp_dir / "cache"
        q_file = temp_dir / "queue.json"
        h_file = temp_dir / "history.json"

        orchestrator = Phase4Orchestrator(
            llm_client=mock_llm,
            rate_limiter=RateLimiter(),
            daily_budget=DailyBudget(budget_file=b_file, cache_dir=c_dir),
            review_queue=ReviewQueueManager(queue_file=q_file, history_file=h_file),
            redactor=PIIRedactor(enabled=True),
        )

        resumes = [
            {
                "resume_id": "cand-01",
                "candidate_name": "Alice Developer",
                "raw_text": "Experience: 5 years Python lead. Engineered MongoDB clusters. Deployed with AWS Lambda.",
            },
            {
                "resume_id": "cand-02",
                "candidate_name": "Bob Junior",
                "raw_text": "Experience: Graphic design, Photoshop, CSS layouts.",
            },
        ]
        phase3_results = {
            "candidates": [
                {"candidate_id": "cand-01", "rerank_rank": 1, "rerank_score": 0.95}
            ]
        }

        results = orchestrator.evaluate_batch(
            jd_id="backend-engineer-001",
            resumes=resumes,
            phase3_results=phase3_results,
            rubric=sample_rubric,
        )

        assert results["status"] == "COMPLETED"
        assert results["total_submitted"] == 2
        assert results["evaluated_count"] == 2
        assert results["auto_decisions"] == 2
        assert results["hr_reports_generated"] == 1
        assert results["candidate_feedbacks_generated"] == 1
