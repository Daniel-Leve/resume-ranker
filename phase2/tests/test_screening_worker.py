"""
Unit tests for api.workers.screening_worker lifecycle transitions, error handling, and isolation.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DATABASE", "test_db")
os.environ.setdefault("MONGODB_COLLECTION", "test_candidate_chunks")

from api.workers.screening_worker import _run_screening, lambda_handler
from phase2.retrieval.fusion import CandidateProvenance
from phase3.reranker.document_builder import ReconstructedDocument


class TestScreeningWorkerValidation:
    def test_missing_screening_run_id(self):
        with pytest.raises(ValueError, match="screening_run_id is required"):
            _run_screening("", "tenant-1", "job-1")

    def test_missing_tenant_id(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            _run_screening("run-1", "   ", "job-1")

    def test_missing_job_id(self):
        with pytest.raises(ValueError, match="job_id is required"):
            _run_screening("run-1", "tenant-1", "")


class TestScreeningWorkerLifecycle:
    @pytest.fixture
    def mock_deps(self):
        with patch("api.workers.screening_worker._get_mongo") as mock_get_mongo, \
             patch("api.workers.screening_worker.embed_texts") as mock_embed, \
             patch("api.workers.screening_worker.lexical_search") as mock_lex, \
             patch("api.workers.screening_worker.vector_search") as mock_vec, \
             patch("api.workers.screening_worker.fuse_results") as mock_fuse, \
             patch("api.workers.screening_worker.build_candidate_document") as mock_build_doc, \
             patch("api.workers.screening_worker.rerank_documents") as mock_rerank, \
             patch("boto3.client") as mock_boto:

            mock_client = MagicMock()
            mock_db = MagicMock()
            mock_collection = MagicMock()
            mock_jobs = MagicMock()
            mock_screening_runs = MagicMock()

            collections = {
                "test_candidate_chunks": mock_collection,
                "candidate_chunks": mock_collection,
                "jobs": mock_jobs,
                "screening_runs": mock_screening_runs,
            }
            mock_db.__getitem__.side_effect = lambda name: collections.get(name, MagicMock())
            mock_client.__getitem__.return_value = mock_db
            mock_get_mongo.return_value = mock_client

            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3

            yield {
                "client": mock_client,
                "db": mock_db,
                "jobs": mock_jobs,
                "screening_runs": mock_screening_runs,
                "collection": mock_collection,
                "embed": mock_embed,
                "lex": mock_lex,
                "vec": mock_vec,
                "fuse": mock_fuse,
                "build_doc": mock_build_doc,
                "rerank": mock_rerank,
                "s3": mock_s3,
            }

    def test_job_description_missing_marks_run_failed(self, mock_deps):
        mock_deps["jobs"].find_one.return_value = None

        with pytest.raises(ValueError, match="Job description not found"):
            _run_screening("run-001", "tenant-acme", "job-999")

        # Verify screening_runs updated to FAILED
        mock_deps["screening_runs"].update_one.assert_any_call(
            {"_id": "run-001"},
            {"$set": pytest.approx_dict({
                "status": "FAILED",
                "error": "Job description not found for job_id=job-999 and tenant_id=tenant-acme",
            })}
        )

    def test_pipeline_exception_marks_run_failed_and_preserves_error(self, mock_deps):
        mock_deps["jobs"].find_one.return_value = {"description": "Senior Backend Engineer Python"}
        mock_deps["embed"].side_effect = RuntimeError("Voyage AI service unavailable")

        with pytest.raises(RuntimeError, match="Voyage AI service unavailable"):
            _run_screening("run-002", "tenant-acme", "job-999")

        # Check status was set to RUNNING_PHASE2 then FAILED
        calls = mock_deps["screening_runs"].update_one.call_args_list
        statuses = [c[0][1]["$set"]["status"] for c in calls]
        assert "RUNNING_PHASE2" in statuses
        assert statuses[-1] == "FAILED"
        assert "Voyage AI service unavailable" in calls[-1][0][1]["$set"]["error"]
        assert "completed_at" in calls[-1][0][1]["$set"]

    def test_empty_phase2_results_completes_with_skipped_phase3(self, mock_deps):
        mock_deps["jobs"].find_one.return_value = {"description": "Backend Engineer"}
        mock_deps["embed"].return_value = [[0.1, 0.2]]
        mock_deps["lex"].return_value = []
        mock_deps["vec"].return_value = []
        mock_deps["fuse"].return_value = []

        _run_screening("run-003", "tenant-acme", "job-101")

        calls = mock_deps["screening_runs"].update_one.call_args_list
        last_update = calls[-1][0][1]["$set"]
        assert last_update["status"] == "COMPLETED"
        assert last_update["phase3_status"] == "SKIPPED"
        assert last_update["candidates"] == []
        assert "completed_at" in last_update
        # Phase 3 rerank should NOT have been called
        mock_deps["rerank"].assert_not_called()

    def test_empty_candidate_documents_completes_with_skipped_phase3(self, mock_deps):
        mock_deps["jobs"].find_one.return_value = {"description": "Backend Engineer"}
        mock_deps["embed"].return_value = [[0.1, 0.2]]

        prov = CandidateProvenance(
            candidate_id="cand-1",
            rrf_score=0.05,
            lexical_rank=1,
            vector_rank=2,
            source_key="s3://test/cand1.json",
            matched_chunks={"c1": "skills"}
        )
        mock_deps["fuse"].return_value = [prov]
        # Document reconstruction returns empty text
        mock_deps["build_doc"].return_value = ReconstructedDocument(
            candidate_id="cand-1",
            text="   ",
            chunk_ids=[],
            truncated=False
        )

        _run_screening("run-004", "tenant-acme", "job-101")

        calls = mock_deps["screening_runs"].update_one.call_args_list
        last_update = calls[-1][0][1]["$set"]
        assert last_update["status"] == "COMPLETED"
        assert last_update["phase3_status"] == "SKIPPED"
        assert last_update["candidates"] == []
        mock_deps["rerank"].assert_not_called()

    def test_successful_screening_workflow_with_strict_scoping(self, mock_deps):
        mock_deps["jobs"].find_one.return_value = {"description": "Backend Engineer"}
        mock_deps["embed"].return_value = [[0.1, 0.2, 0.3]]

        prov = CandidateProvenance(
            candidate_id="cand-good",
            rrf_score=0.08,
            lexical_rank=1,
            vector_rank=1,
            source_key="extracted/cand-good.json",
            matched_chunks={"chunk-1": "summary"}
        )
        mock_deps["fuse"].return_value = [prov]
        mock_deps["build_doc"].return_value = ReconstructedDocument(
            candidate_id="cand-good",
            text="[SUMMARY]\nExpert Python Engineer",
            chunk_ids=["chunk-1"],
            truncated=False
        )
        mock_deps["rerank"].return_value = [
            {"index": 0, "relevance_score": 0.95}
        ]

        _run_screening("run-005", "tenant-acme", "job-101")

        # Verify scoping on lexical search, vector search, and build_candidate_document
        mock_deps["lex"].assert_called_once_with(
            mock_deps["collection"],
            "Backend Engineer",
            top_k=pytest.approx(mock_deps["lex"].call_args[1]["top_k"]),
            tenant_id="tenant-acme",
            job_id="job-101"
        )
        mock_deps["vec"].assert_called_once_with(
            mock_deps["collection"],
            [0.1, 0.2, 0.3],
            top_k=pytest.approx(mock_deps["vec"].call_args[1]["top_k"]),
            tenant_id="tenant-acme",
            job_id="job-101"
        )
        mock_deps["build_doc"].assert_called_once_with(
            mock_deps["collection"],
            "cand-good",
            tenant_id="tenant-acme",
            job_id="job-101"
        )

        # Verify terminal status is COMPLETED
        calls = mock_deps["screening_runs"].update_one.call_args_list
        last_update = calls[-1][0][1]["$set"]
        assert last_update["status"] == "COMPLETED"
        assert last_update["phase3_status"] == "COMPLETED"
        assert len(last_update["candidates"]) == 1
        assert last_update["candidates"][0]["candidate_id"] == "cand-good"
        assert last_update["candidates"][0]["rerank_score"] == 0.95
        assert "completed_at" in last_update

        # Verify S3 artifact upload
        mock_deps["s3"].put_object.assert_called_once()
        s3_call = mock_deps["s3"].put_object.call_args[1]
        from api.workers.screening_worker import S3_BUCKET
        assert s3_call["Bucket"] == S3_BUCKET
        assert s3_call["Key"] == "tenants/tenant-acme/jobs/job-101/screening/run-005-reranked.json"


class TestScreeningWorkerLambdaHandler:
    @patch("api.workers.screening_worker._run_screening")
    def test_lambda_handler_success(self, mock_run):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": json.dumps({
                        "screening_run_id": "run-1",
                        "tenant_id": "tenant-1",
                        "job_id": "job-1",
                    })
                }
            ]
        }
        res = lambda_handler(event, None)
        assert res == {"batchItemFailures": []}
        mock_run.assert_called_once_with(
            screening_run_id="run-1",
            tenant_id="tenant-1",
            job_id="job-1",
        )

    @patch("api.workers.screening_worker._run_screening", side_effect=Exception("Database down"))
    def test_lambda_handler_reports_batch_item_failure(self, mock_run):
        event = {
            "Records": [
                {
                    "messageId": "msg-fail",
                    "body": json.dumps({
                        "screening_run_id": "run-2",
                        "tenant_id": "tenant-1",
                        "job_id": "job-1",
                    })
                }
            ]
        }
        res = lambda_handler(event, None)
        assert res == {"batchItemFailures": [{"itemIdentifier": "msg-fail"}]}


# Helper for partial dict matching
class approx_dict:
    def __init__(self, expected):
        self.expected = expected

    def __eq__(self, actual):
        if not isinstance(actual, dict):
            return False
        return all(actual.get(k) == v for k, v in self.expected.items())

    def __repr__(self):
        return repr(self.expected)

pytest.approx_dict = approx_dict
