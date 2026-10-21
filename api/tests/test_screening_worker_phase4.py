"""
Unit tests verifying Phase 4 integration in api/workers/screening_worker.py.
"""
import pytest
from unittest.mock import MagicMock, patch

from api.workers.screening_worker import _run_screening
from phase2.retrieval.fusion import CandidateProvenance
from phase3.reranker.document_builder import ReconstructedDocument
from phase4.schemas import JobRubric, RubricCriterion


class TestScreeningWorkerPhase4Integration:
    """Verifies that an approved rubric triggers Phase 4 evaluation and generates HR reports."""

    def test_run_screening_executes_phase4_when_rubric_approved(self):
        approved_rubric = JobRubric(
            jd_id="job-101",
            version="v1",
            status="APPROVED",
            criteria=[
                RubricCriterion(
                    id="c1",
                    description="5+ years Python lead experience",
                    type="must",
                    weight=0.6,
                    how_to_verify="Look for Python lead experience in resume",
                ),
                RubricCriterion(
                    id="c2",
                    description="AWS Lambda and serverless deployment",
                    type="nice",
                    weight=0.4,
                    how_to_verify="Look for AWS Lambda or serverless",
                ),
            ],
        )

        job_doc = {
            "_id": "job-101",
            "tenant_id": "tenant-test",
            "description": "Looking for Senior Python Lead with AWS Lambda experience.",
            "rubric_status": "APPROVED",
            "rubric": approved_rubric.model_dump(),
            "final_shortlisted_candidates_count": 1,
        }

        app_doc = {
            "_id": "app-001",
            "candidate_id": "cand-001",
            "job_id": "job-101",
            "tenant_id": "tenant-test",
            "candidate_name": "Daniel Leve",
            "s3_resume_key": "incoming/daniel.pdf",
            "status": "INDEXED",
        }

        screening_run_doc = {
            "_id": "run-test-p4",
            "screening_run_id": "run-test-p4",
            "tenant_id": "tenant-test",
            "job_id": "job-101",
            "status": "QUEUED",
        }

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.side_effect = lambda name: {
            "jobs": mock_jobs_col,
            "applications": mock_apps_col,
            "screening_runs": mock_runs_col,
            "candidate_chunks": mock_collection,
        }.get(name, MagicMock())

        mock_jobs_col = MagicMock()
        mock_jobs_col.find_one.return_value = job_doc

        mock_apps_col = MagicMock()
        mock_apps_col.find.return_value = [app_doc]
        mock_apps_col.count_documents.return_value = 1

        mock_runs_col = MagicMock()
        mock_runs_col.find_one.return_value = screening_run_doc

        mock_prov = CandidateProvenance(
            candidate_id="cand-001",
            rrf_score=0.95,
            lexical_rank=1,
            vector_rank=1,
            matched_chunks={"c1": "Experience"},
            source_key="s3://test/resume.pdf",
        )

        mock_doc = ReconstructedDocument(
            candidate_id="cand-001",
            text="Daniel Leve. 6 years Python Lead. Deployed microservices on AWS Lambda.",
            chunk_ids=["c1"],
            truncated=False,
        )

        mock_rerank = [{"index": 0, "relevance_score": 0.98}]

        # Mock Phase4Orchestrator to return a synthetic evaluate_batch output
        mock_p4_eval_result = {
            "job_id": "job-101",
            "status": "COMPLETED",
            "evaluated_count": 1,
            "auto_decisions": 1,
            "human_review_queue": 0,
            "candidate_results": {
                "cand-001": {
                    "candidate_id": "cand-001",
                    "application_id": "app-001",
                    "decision": "SHORTLISTED",
                    "weighted_score": 0.95,
                    "reconciliation": {"decision": "AUTO", "weighted_score": 0.95},
                    "hr_report": {
                        "candidate_id": "cand-001",
                        "job_id": "job-101",
                        "decision": "SHORTLISTED",
                        "final_score": 95.0,
                        "rubric_version": "v1",
                        "criteria_scores": [
                            {"criterion_name": "5+ years Python lead experience", "score": 5, "evidence_quote": "6 years Python Lead"}
                        ],
                        "interview_questions": ["Describe your Lambda deployment architecture."],
                    },
                }
            },
        }

        with patch("api.workers.screening_worker._get_mongo", return_value=mock_client), \
             patch("api.workers.screening_worker.embed_texts", return_value=[[0.1] * 1024]), \
             patch("api.workers.screening_worker.lexical_search", return_value=[mock_prov]), \
             patch("api.workers.screening_worker.vector_search", return_value=[mock_prov]), \
             patch("api.workers.screening_worker.fuse_results", return_value=[mock_prov]), \
             patch("api.workers.screening_worker.build_candidate_document", return_value=mock_doc), \
             patch("api.workers.screening_worker.rerank_documents", return_value=mock_rerank), \
             patch("phase4.orchestrator.Phase4Orchestrator.evaluate_batch", return_value=mock_p4_eval_result), \
             patch("boto3.client") as mock_boto:

            mock_boto.return_value = MagicMock()
            _run_screening("run-test-p4", "tenant-test", "job-101", final_shortlisted_candidates_count=1)

        # Verify screening_runs updated with COMPLETED phase4_status and candidate has hr_report and decision
        update_calls = mock_runs_col.update_one.call_args_list
        assert len(update_calls) > 0
        final_call_payload = update_calls[-1][0][1]["$set"]
        assert final_call_payload["phase3_status"] == "COMPLETED"
        assert final_call_payload["phase4_status"] == "COMPLETED"
        assert len(final_call_payload["candidates"]) == 1

        top_cand = final_call_payload["candidates"][0]
        assert top_cand["decision"] == "SHORTLISTED"
        assert top_cand["final_score"] == 0.95
        assert "hr_report" in top_cand
        assert top_cand["hr_report"]["final_score"] == 95.0

        # Verify application document updated with SHORTLISTED decision, phase statuses, and hr_report
        assert mock_apps_col.update_one.called
        app_call_args = mock_apps_col.update_one.call_args
        assert app_call_args[0][0] == {"_id": "app-001"}
        app_update_set = app_call_args[0][1]["$set"]
        assert app_update_set["phase3_status"] == "COMPLETED"
        assert app_update_set["phase4_status"] == "COMPLETED"
        assert app_update_set["decision"] == "SHORTLISTED"
        assert app_update_set["status"] == "SHORTLISTED"
        assert app_update_set["screening_run_id"] == "run-test-p4"
        assert app_update_set["screened_at"] in app_update_set or "screened_at" in app_update_set
        assert app_update_set["hr_report"] == mock_p4_eval_result["candidate_results"]["cand-001"]["hr_report"]

    def test_run_screening_routes_candidate_with_missing_must_haves_to_human_review(self):
        approved_rubric = JobRubric(
            jd_id="job-101",
            version="v1",
            status="APPROVED",
            criteria=[
                RubricCriterion(
                    id="c1",
                    description="5+ years Python lead experience",
                    type="must",
                    weight=1.0,
                    how_to_verify="Look for Python lead experience in resume",
                ),
            ],
        )

        job_doc = {
            "_id": "job-101",
            "tenant_id": "tenant-test",
            "description": "Looking for Senior Python Lead.",
            "rubric_status": "APPROVED",
            "rubric": approved_rubric.model_dump(),
            "final_shortlisted_candidates_count": 1,
        }

        app_doc = {
            "_id": "app-002",
            "candidate_id": "cand-daniel",
            "job_id": "job-101",
            "tenant_id": "tenant-test",
            "candidate_name": "Daniel Leve",
            "s3_resume_key": "incoming/daniel.pdf",
            "status": "INDEXED",
        }

        screening_run_doc = {
            "_id": "run-test-daniel",
            "screening_run_id": "run-test-daniel",
            "tenant_id": "tenant-test",
            "job_id": "job-101",
            "status": "QUEUED",
        }

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.side_effect = lambda name: {
            "jobs": mock_jobs_col,
            "applications": mock_apps_col,
            "screening_runs": mock_runs_col,
            "candidate_chunks": MagicMock(),
        }.get(name, MagicMock())

        mock_jobs_col = MagicMock()
        mock_jobs_col.find_one.return_value = job_doc

        mock_apps_col = MagicMock()
        mock_apps_col.find.return_value = [app_doc]
        mock_apps_col.count_documents.return_value = 1

        mock_runs_col = MagicMock()
        mock_runs_col.find_one.return_value = screening_run_doc

        mock_prov = CandidateProvenance(
            candidate_id="cand-daniel",
            rrf_score=0.95,
            lexical_rank=1,
            vector_rank=1,
            matched_chunks={"c1": "Experience"},
            source_key="s3://test/resume.pdf",
        )

        mock_doc = ReconstructedDocument(
            candidate_id="cand-daniel",
            text="Daniel Leve. Entry level. No Python.",
            chunk_ids=["c1"],
            truncated=False,
        )

        mock_rerank = [{"index": 0, "relevance_score": 0.42}]

        # Candidate ranked #1 in search but failed must-have -> HUMAN_REVIEW, UNDECIDED
        mock_p4_eval_result = {
            "job_id": "job-101",
            "status": "COMPLETED",
            "evaluated_count": 1,
            "auto_decisions": 0,
            "human_review_queue": 1,
            "candidate_results": {
                "cand-daniel": {
                    "candidate_id": "cand-daniel",
                    "application_id": "app-002",
                    "decision": "UNDECIDED",
                    "review_status": "HUMAN_REVIEW",
                    "weighted_score": 0.0,
                    "reconciliation": {"decision": "HUMAN_REVIEW", "weighted_score": 0.0},
                    "hr_report": {
                        "candidate_id": "cand-daniel",
                        "job_id": "job-101",
                        "decision": "UNDECIDED",
                        "final_score": 0.0,
                        "rubric_version": "v1",
                        "criteria_scores": [
                            {"criterion_name": "5+ years Python lead experience", "score": 1, "evidence_quote": "Not evidenced in resume"}
                        ],
                    },
                }
            },
        }

        with patch("api.workers.screening_worker._get_mongo", return_value=mock_client), \
             patch("api.workers.screening_worker.embed_texts", return_value=[[0.1] * 1024]), \
             patch("api.workers.screening_worker.lexical_search", return_value=[mock_prov]), \
             patch("api.workers.screening_worker.vector_search", return_value=[mock_prov]), \
             patch("api.workers.screening_worker.fuse_results", return_value=[mock_prov]), \
             patch("api.workers.screening_worker.build_candidate_document", return_value=mock_doc), \
             patch("api.workers.screening_worker.rerank_documents", return_value=mock_rerank), \
             patch("phase4.orchestrator.Phase4Orchestrator.evaluate_batch", return_value=mock_p4_eval_result), \
             patch("boto3.client") as mock_boto:

            mock_boto.return_value = MagicMock()
            _run_screening("run-test-daniel", "tenant-test", "job-101", final_shortlisted_candidates_count=1)

        # Verify application status set to NEEDS_REVIEW (not SHORTLISTED)
        assert mock_apps_col.update_one.called
        app_call_args = mock_apps_col.update_one.call_args
        assert app_call_args[0][0] == {"_id": "app-002"}
        app_update_set = app_call_args[0][1]["$set"]
        assert app_update_set["decision"] == "UNDECIDED"
        assert app_update_set["status"] == "NEEDS_REVIEW"
        assert app_update_set["phase3_status"] == "COMPLETED"
        assert app_update_set["phase4_status"] == "COMPLETED"
        assert "hr_report" in app_update_set
        assert app_update_set["hr_report"]["criteria_scores"][0]["evidence_quote"] == "Not evidenced in resume"
