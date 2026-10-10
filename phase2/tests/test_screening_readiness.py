"""
Unit tests for screening readiness validation and conflict handling in api.handlers.application_handler.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure required environment variables exist prior to handler import
os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SCREENING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789012/screening-queue")

from api.handlers.application_handler import _post_screening


class TestScreeningReadiness:
    @pytest.fixture
    def mock_db_and_mongo(self):
        with patch("api.handlers.application_handler._get_mongo") as mock_get_mongo:
            mock_client = MagicMock()
            mock_db = MagicMock()
            collections = {
                "jobs": MagicMock(),
                "screening_runs": MagicMock(),
                "applications": MagicMock(),
                "tenants": MagicMock(),
            }
            mock_db.__getitem__.side_effect = lambda name: collections.get(name, MagicMock())
            mock_client.__getitem__.return_value = mock_db
            mock_get_mongo.return_value.__enter__.return_value = mock_client
            yield collections

    def test_missing_job_id_returns_400(self):
        event = {"pathParameters": {}}
        response = _post_screening(event)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "job_id path parameter missing" in body["error"]

    def test_job_not_found_returns_404(self, mock_db_and_mongo):
        mock_db_and_mongo["jobs"].find_one.return_value = None

        event = {"pathParameters": {"job_id": "job-nonexistent"}}
        response = _post_screening(event)
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert "Job not found" in body["error"]

    def test_active_run_in_progress_returns_409(self, mock_db_and_mongo):
        mock_db_and_mongo["jobs"].find_one.return_value = {
            "_id": "job-101",
            "tenant_id": "tenant-acme",
            "status": "OPEN",
        }
        mock_db_and_mongo["screening_runs"].find_one.return_value = {
            "_id": "run-active-001",
            "screening_run_id": "run-active-001",
            "status": "RUNNING_PHASE2",
        }

        event = {"pathParameters": {"job_id": "job-101"}}
        response = _post_screening(event)
        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert body["code"] == "SCREENING_ALREADY_IN_PROGRESS"
        assert body["screening_run_id"] == "run-active-001"
        assert body["status"] == "RUNNING_PHASE2"

    def test_no_applications_at_all_returns_409_no_applications(self, mock_db_and_mongo):
        mock_db_and_mongo["jobs"].find_one.return_value = {
            "_id": "job-101",
            "tenant_id": "tenant-acme",
        }
        mock_db_and_mongo["screening_runs"].find_one.return_value = None
        # count_documents called first for indexed_count -> returns 0
        # then called for total_count -> returns 0
        mock_db_and_mongo["applications"].count_documents.side_effect = [0, 0]

        event = {"pathParameters": {"job_id": "job-101"}}
        response = _post_screening(event)
        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert body["code"] == "NO_APPLICATIONS"
        assert body["eligible_candidate_count"] == 0
        assert body["total_application_count"] == 0

    def test_applications_exist_but_none_indexed_returns_409_not_indexed(self, mock_db_and_mongo):
        mock_db_and_mongo["jobs"].find_one.return_value = {
            "_id": "job-101",
            "tenant_id": "tenant-acme",
        }
        mock_db_and_mongo["screening_runs"].find_one.return_value = None
        # indexed_count = 0, total_count = 3
        mock_db_and_mongo["applications"].count_documents.side_effect = [0, 3]

        event = {"pathParameters": {"job_id": "job-101"}}
        response = _post_screening(event)
        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert body["code"] == "APPLICATIONS_NOT_INDEXED"
        assert body["eligible_candidate_count"] == 0
        assert body["total_application_count"] == 3

    @patch("boto3.client")
    def test_indexed_applications_success_returns_202_and_enqueues_sqs(
        self, mock_boto_client, mock_db_and_mongo
    ):
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs

        mock_db_and_mongo["jobs"].find_one.return_value = {
            "_id": "job-101",
            "tenant_id": "tenant-acme",
        }
        mock_db_and_mongo["screening_runs"].find_one.return_value = None
        # indexed_count = 5
        mock_db_and_mongo["applications"].count_documents.return_value = 5

        event = {"pathParameters": {"job_id": "job-101"}}
        response = _post_screening(event)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["status"] == "QUEUED"
        assert body["eligible_candidate_count"] == 5
        assert "screening_run_id" in body

        # Verify SQS message sent with proper tenant and job scoping
        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789012/screening-queue"
        sqs_body = json.loads(call_kwargs["MessageBody"])
        assert sqs_body["screening_run_id"] == body["screening_run_id"]
        assert sqs_body["tenant_id"] == "tenant-acme"
        assert sqs_body["job_id"] == "job-101"

        # Verify screening_runs document created in MongoDB
        mock_db_and_mongo["screening_runs"].insert_one.assert_called_once()
        inserted_doc = mock_db_and_mongo["screening_runs"].insert_one.call_args[0][0]
        assert inserted_doc["_id"] == body["screening_run_id"]
        assert inserted_doc["tenant_id"] == "tenant-acme"
        assert inserted_doc["job_id"] == "job-101"
        assert inserted_doc["status"] == "QUEUED"
        assert inserted_doc["eligible_candidate_count"] == 5
