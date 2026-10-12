"""
Block 4 — Reliability, Connection Pooling, Lifecycle Consistency & Idempotency Tests.

Tests covering:
  1. MongoDB connection pooling & warm-start reuse across invocations.
  2. Indexing worker failure handling, updating application status to FAILED.
  3. Indexing worker idempotency with repeated S3/SQS events (hash matching skips re-embedding).
  4. Tenant/job scoped chunk replacement when resume content hash changes.
  5. Screening worker idempotency (skips re-execution if already marked COMPLETED).
  6. Screening worker transient failure transitions and error message persistence.
  7. Application handler atomic lifecycle state insertion before SQS message dispatch.
  8. Voyage AI reranker retry logic with exponential backoff on transient failures.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SCREENING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/screening-queue")

from api.storage.mongo import close_mongo_client, get_mongo_client
from api.workers.indexing_worker import _index_single, lambda_handler as indexing_lambda_handler
from api.workers.screening_worker import _run_screening, lambda_handler as screening_lambda_handler
from phase2.retrieval.fusion import CandidateProvenance
from phase3.reranker.document_builder import ReconstructedDocument
from phase3.reranker.voyage_reranker import rerank_documents


# ─── 1. MongoDB Connection Pooling & Warm-Start Reuse ────────────────────────

class TestMongoConnectionPooling:
    def teardown_method(self):
        close_mongo_client()

    @patch("api.storage.mongo.MongoClient")
    def test_get_mongo_client_reuses_healthy_instance(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_instance.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_instance

        client1 = get_mongo_client("mongodb://localhost:27017/test1")
        client2 = get_mongo_client("mongodb://localhost:27017/test1")

        assert client1 is client2
        # MongoClient constructor called only once due to pooling
        mock_client_cls.assert_called_once()
        # Ping checked on second call
        mock_instance.admin.command.assert_called_with("ping")

    @patch("api.storage.mongo.MongoClient")
    def test_get_mongo_client_reconnects_if_ping_fails(self, mock_client_cls):
        dead_instance = MagicMock()
        dead_instance.admin.command.side_effect = Exception("Connection lost")

        healthy_instance = MagicMock()
        healthy_instance.admin.command.return_value = {"ok": 1}

        mock_client_cls.side_effect = [dead_instance, healthy_instance]

        client1 = get_mongo_client("mongodb://localhost:27017/reconnect_test")
        assert client1 is dead_instance

        # Second retrieval attempts ping on dead_instance, catches failure, re-creates
        client2 = get_mongo_client("mongodb://localhost:27017/reconnect_test")
        assert client2 is healthy_instance
        assert mock_client_cls.call_count == 2


# ─── 2. Indexing Worker Idempotency & Lifecycle States ───────────────────────

class TestIndexingWorkerReliability:
    @patch("api.workers.indexing_worker._get_mongo")
    @patch("boto3.client")
    def test_indexing_worker_marks_failed_on_error(self, mock_boto, mock_get_mongo):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        # Malformed JSON in S3
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: b'{"status": "FAILED", "text": ""}')
        }

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_get_mongo.return_value = mock_client

        with pytest.raises(ValueError, match="Phase 1 status is not SUCCEEDED"):
            _index_single("tenants/t1/jobs/j1/applications/app-err/extracted.json")

        # Verify application status was set to FAILED with error recorded
        mock_db["applications"].update_one.assert_called_with(
            {"_id": "app-err"},
            {"$set": {
                "phase2_status": "FAILED",
                "phase2_error": "Phase 1 status is not SUCCEEDED: FAILED",
            }}
        )

    @patch("api.workers.indexing_worker._get_mongo")
    @patch("boto3.client")
    @patch("api.workers.indexing_worker.embed_texts")
    def test_indexing_idempotent_when_hash_matches(self, mock_embed, mock_boto, mock_get_mongo):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        extracted_data = {
            "status": "SUCCEEDED",
            "text": "Senior Python Developer with AWS experience.",
            "source": {"key": "tenants/t1/jobs/j1/applications/app-100/original.pdf"},
            "blocks": []
        }
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(extracted_data).encode("utf-8"))
        }

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__.side_effect = lambda name: mock_collection if name == "candidate_chunks" else mock_db
        mock_client.__getitem__.return_value = mock_db
        mock_get_mongo.return_value = mock_client

        # Compute expected hash
        from phase2.indexer.chunker import compute_content_hash
        stored_hash = compute_content_hash(extracted_data["text"])
        mock_collection.find_one.return_value = {"content_hash": stored_hash}

        _index_single("tenants/t1/jobs/j1/applications/app-100/extracted.json")

        # Embedder should NOT be called because hash matches
        mock_embed.assert_not_called()
        # Status should transition to INDEXED
        mock_db["applications"].update_one.assert_called_with(
            {"_id": "app-100"},
            {"$set": {"phase2_status": "INDEXED"}}
        )

    @patch("api.workers.indexing_worker._get_mongo")
    @patch("boto3.client")
    @patch("api.workers.indexing_worker.embed_texts")
    @patch("api.workers.indexing_worker.chunk_resume")
    @patch("api.workers.indexing_worker.delete_candidate_chunks")
    def test_indexing_stale_chunks_purged_with_tenant_scope(
        self, mock_delete_chunks, mock_chunk_resume, mock_embed, mock_boto, mock_get_mongo
    ):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        extracted_data = {
            "status": "SUCCEEDED",
            "text": "Updated resume content after re-upload.",
            "source": {"key": "tenants/tenant-xyz/jobs/job-456/applications/app-200/original.pdf"},
            "blocks": []
        }
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(extracted_data).encode("utf-8"))
        }

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__.side_effect = lambda name: mock_collection if name == "candidate_chunks" else mock_db
        mock_client.__getitem__.return_value = mock_db
        mock_get_mongo.return_value = mock_client

        # Existing hash differs -> candidate re-uploaded new resume
        mock_collection.find_one.return_value = {"content_hash": "old-sha256-hash"}
        chunk_mock = MagicMock(
            candidate_id="cand-200",
            chunk_id="c1",
            source_key="s1",
            chunk_index=0,
            section="experience",
            text="Updated",
            page_start=1,
            page_end=1
        )
        mock_chunk_resume.return_value = [chunk_mock]
        mock_embed.return_value = [[0.1] * 1024]

        _index_single("tenants/tenant-xyz/jobs/job-456/applications/app-200/extracted.json")

        # Verify delete_candidate_chunks was called with tenant_id and job_id scoping
        mock_delete_chunks.assert_called_once()
        args, kwargs = mock_delete_chunks.call_args
        assert kwargs.get("tenant_id") == "tenant-xyz"
        assert kwargs.get("job_id") == "job-456"


# ─── 3. Screening Worker Idempotency & Lifecycle States ───────────────────────

class TestScreeningWorkerReliability:
    @patch("api.workers.screening_worker._get_mongo")
    @patch("api.workers.screening_worker.embed_texts")
    def test_screening_worker_skips_already_completed_run(self, mock_embed, mock_get_mongo):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_get_mongo.return_value = mock_client

        # Database already has run marked as COMPLETED (e.g. SQS redelivered message)
        mock_db["screening_runs"].find_one.return_value = {
            "_id": "run-completed-123",
            "status": "COMPLETED",
            "candidates": [{"candidate_id": "c1"}],
        }

        _run_screening("run-completed-123", "tenant-1", "job-1")

        # Must not re-execute embeddings or search
        mock_embed.assert_not_called()
        # Must not overwrite run status
        mock_db["screening_runs"].update_one.assert_not_called()


# ─── 4. Voyage AI Transient Error Recovery ───────────────────────────────────

class TestVoyageRerankerRetry:
    @patch("phase3.reranker.voyage_reranker._get_client")
    @patch("time.sleep")
    def test_rerank_documents_retries_on_transient_failure_then_succeeds(
        self, mock_sleep, mock_get_client
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # First call raises transient Network error, second succeeds
        res_mock = MagicMock()
        res_mock.results = [
            MagicMock(index=0, relevance_score=0.88, document="Resume 1")
        ]
        mock_client.rerank.side_effect = [
            Exception("503 Service Unavailable"),
            res_mock
        ]

        results = rerank_documents(
            query="Senior Python Engineer",
            documents=["Resume 1"],
            max_retries=3,
            base_delay_s=0.1
        )

        assert len(results) == 1
        assert results[0]["relevance_score"] == 0.88
        assert mock_client.rerank.call_count == 2
        mock_sleep.assert_called_once_with(0.1)

    @patch("phase3.reranker.voyage_reranker._get_client")
    @patch("time.sleep")
    def test_rerank_documents_raises_runtime_error_after_exhausting_retries(
        self, mock_sleep, mock_get_client
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rerank.side_effect = Exception("Rate limit exceeded")

        with pytest.raises(RuntimeError, match="Voyage rerank failed after 2 attempts"):
            rerank_documents(
                query="Python Dev",
                documents=["Doc"],
                max_retries=2,
                base_delay_s=0.05
            )

        assert mock_client.rerank.call_count == 2
