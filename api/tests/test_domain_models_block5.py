"""
Block 5 — Domain Model & Relationships Tests.

Tests covering:
1. Application-to-Job and Application-to-Candidate relationships.
2. Resume version tracking and immutable resume version history in applications.
3. CandidateChunk schema validation with resume_version, tenant_id, job_id, application_id.
4. Indexing worker associating chunks with application candidate_id and resume_version.
5. Screening worker referencing input application IDs and enriching output with application_id and candidate_name.
6. Migration utility idempotency, dry-run reporting, and backward-compatibility with legacy documents.
7. Domain database indexes creation and constraint verification.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SCREENING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/screening-queue")

from api.handlers.application_handler import _post_application
from api.storage.indexes import ensure_domain_indexes
from api.storage.migration import migrate_domain_models
from api.workers.indexing_worker import _index_single
from api.workers.screening_worker import _run_screening
from phase2.models.schemas import CandidateChunk
from phase2.retrieval.fusion import CandidateProvenance
from phase3.reranker.document_builder import ReconstructedDocument


# ─── 1. Application Domain Model & Relationships ─────────────────────────────

class TestApplicationDomainModel:
    @patch("boto3.client")
    @patch("api.handlers.application_handler._get_mongo")
    def test_post_application_creates_candidate_and_version_1(self, mock_get_mongo, mock_boto):
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/test-url"
        mock_boto.return_value = mock_s3

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_get_mongo.return_value = mock_client

        # Job exists and is open
        mock_db["jobs"].find_one.return_value = {"_id": "job-101", "tenant_id": "tenant-acme", "status": "OPEN"}

        event = {
            "pathParameters": {"job_id": "job-101"},
            "body": json.dumps({"candidate_name": "Daniel Leve"}),
            "requestContext": {}
        }

        resp = _post_application(event)
        assert resp["statusCode"] == 201

        # Verify application document inserted into MongoDB
        mock_db["applications"].insert_one.assert_called_once()
        inserted_app = mock_db["applications"].insert_one.call_args[0][0]

        assert inserted_app["tenant_id"] == "tenant-acme"
        assert inserted_app["job_id"] == "job-101"
        assert inserted_app["candidate_id"] == "daniel-leve"
        assert inserted_app["candidate_name"] == "Daniel Leve"
        assert inserted_app["current_resume_version"] == 1
        assert len(inserted_app["resume_versions"]) == 1
        assert inserted_app["resume_versions"][0]["version"] == 1
        assert inserted_app["resume_versions"][0]["status"] == "PENDING_UPLOAD"
        assert "s3_resume_key" in inserted_app["resume_versions"][0]


# ─── 2. CandidateChunk Schema & Indexing Worker Association ──────────────────

class TestCandidateChunkDomainRelationships:
    def test_candidate_chunk_to_mongo_doc_includes_resume_version(self):
        chunk = CandidateChunk(
            candidate_id="cand-001",
            chunk_id="cand-001_exp_00",
            source_key="s3://test/extracted.json",
            chunk_index=0,
            section="experience",
            text="Python engineer",
            embedding_model="voyage-4-large",
            embedding_dimensions=1024,
            embedding=[0.1] * 1024,
            content_hash="abc123hash",
            tenant_id="tenant-acme",
            job_id="job-99",
            application_id="app-777",
            resume_version=2,
        )
        doc = chunk.to_mongo_doc()
        assert doc["tenant_id"] == "tenant-acme"
        assert doc["job_id"] == "job-99"
        assert doc["application_id"] == "app-777"
        assert doc["resume_version"] == 2

    @patch("api.workers.indexing_worker._get_mongo")
    @patch("boto3.client")
    @patch("api.workers.indexing_worker.embed_texts")
    @patch("api.workers.indexing_worker.chunk_resume")
    def test_indexing_worker_attaches_application_candidate_id_and_version(
        self, mock_chunk_resume, mock_embed, mock_boto, mock_get_mongo
    ):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        extracted_data = {
            "status": "SUCCEEDED",
            "text": "Full stack engineer resume.",
            "source": {"key": "tenants/t1/jobs/j1/applications/app-555/original.pdf"},
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

        # Application has candidate_id 'alice-smith' and current_resume_version = 3
        mock_db["applications"].find_one.return_value = {
            "_id": "app-555",
            "candidate_id": "alice-smith",
            "current_resume_version": 3,
        }
        mock_collection.find_one.return_value = None  # No existing hash

        mock_chunk_resume.return_value = [
            MagicMock(
                candidate_id="alice-smith",
                chunk_id="alice-smith_summary_00",
                source_key="s3://key",
                chunk_index=0,
                section="summary",
                text="Python Dev",
                page_start=1,
                page_end=1
            )
        ]
        mock_embed.return_value = [[0.2] * 1024]

        with patch("api.workers.indexing_worker.upsert_chunks") as mock_upsert:
            _index_single("tenants/t1/jobs/j1/applications/app-555/extracted.json")

            mock_upsert.assert_called_once()
            stored_docs = mock_upsert.call_args[0][1]
            assert len(stored_docs) == 1
            assert stored_docs[0]["candidate_id"] == "alice-smith"
            assert stored_docs[0]["application_id"] == "app-555"
            assert stored_docs[0]["resume_version"] == 3

        # Verify application resume_versions array was updated with INDEXED status
        calls = mock_db["applications"].update_one.call_args_list
        version_update_calls = [
            c for c in calls
            if c[0][0].get("resume_versions.version") == 3
        ]
        assert len(version_update_calls) == 1
        set_payload = version_update_calls[0][0][1]["$set"]
        assert set_payload["resume_versions.$.status"] == "INDEXED"
        assert "resume_versions.$.indexed_at" in set_payload


# ─── 3. Screening Worker Domain Enrichment ───────────────────────────────────

class TestScreeningWorkerDomainEnrichment:
    @patch("api.workers.screening_worker._get_mongo")
    @patch("api.workers.screening_worker.embed_texts")
    @patch("api.workers.screening_worker.lexical_search")
    @patch("api.workers.screening_worker.vector_search")
    @patch("api.workers.screening_worker.fuse_results")
    @patch("api.workers.screening_worker.build_candidate_document")
    @patch("api.workers.screening_worker.rerank_documents")
    @patch("boto3.client")
    def test_screening_worker_enriches_output_with_application_and_candidate_name(
        self, mock_boto, mock_rerank, mock_build_doc, mock_fuse, mock_vec, mock_lex, mock_embed, mock_get_mongo
    ):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__.side_effect = lambda name: mock_collection if name == "candidate_chunks" else mock_db
        mock_client.__getitem__.return_value = mock_db
        mock_get_mongo.return_value = mock_client

        mock_db["screening_runs"].find_one.return_value = None  # Not completed
        mock_db["jobs"].find_one.return_value = {"description": "Lead Python Architect"}
        mock_embed.return_value = [[0.1] * 1024]

        prov = CandidateProvenance(
            candidate_id="daniel-leve",
            rrf_score=0.12,
            lexical_rank=1,
            vector_rank=1,
            source_key="s3://test/extracted.json",
            matched_chunks={"c1": "experience"}
        )
        mock_fuse.return_value = [prov]
        mock_build_doc.return_value = ReconstructedDocument(
            candidate_id="daniel-leve",
            text="Experienced Python Architect",
            chunk_ids=["c1"],
            truncated=False
        )
        mock_rerank.return_value = [{"index": 0, "relevance_score": 0.94}]

        # Applications collection has candidate_id 'daniel-leve' mapped to application_id 'app-abc'
        mock_db["applications"].find.return_value = [
            {"_id": "app-abc", "candidate_id": "daniel-leve", "candidate_name": "Daniel Leve"}
        ]

        _run_screening("run-999", "tenant-acme", "job-101")

        calls = mock_db["screening_runs"].update_one.call_args_list
        last_update = calls[-1][0][1]["$set"]
        assert last_update["status"] == "COMPLETED"
        assert len(last_update["candidates"]) == 1
        cand_result = last_update["candidates"][0]
        assert cand_result["candidate_id"] == "daniel-leve"
        assert cand_result["application_id"] == "app-abc"
        assert cand_result["candidate_name"] == "Daniel Leve"
        assert cand_result["rerank_score"] == 0.94


# ─── 4. Database Domain Indexes ──────────────────────────────────────────────

class TestDomainIndexes:
    def test_ensure_domain_indexes_creates_required_indexes(self):
        mock_db = MagicMock()
        cols = {
            "tenants": MagicMock(),
            "tenant_memberships": MagicMock(),
            "jobs": MagicMock(),
            "applications": MagicMock(),
            "screening_runs": MagicMock(),
            "candidate_chunks": MagicMock(),
        }
        mock_db.__getitem__.side_effect = lambda name: cols[name]

        res = ensure_domain_indexes(mock_db)
        assert "tenants" in res
        assert "applications" in res
        assert "candidate_chunks" in res

        # Verify compound indexes were created
        cols["applications"].create_index.assert_any_call(
            [("tenant_id", 1), ("job_id", 1), ("phase2_status", 1)],
            name="idx_apps_tenant_job_phase2_status"
        )
        cols["candidate_chunks"].create_index.assert_any_call(
            [("tenant_id", 1), ("job_id", 1), ("candidate_id", 1)],
            name="idx_tenant_job_candidate"
        )


# ─── 5. Migration & Backward Compatibility ───────────────────────────────────

class TestDomainMigration:
    def test_migrate_domain_models_dry_run_does_not_modify(self):
        mock_db = MagicMock()
        mock_apps = MagicMock()
        mock_runs = MagicMock()
        mock_chunks = MagicMock()

        mock_db.__getitem__.side_effect = lambda name: {
            "applications": mock_apps,
            "screening_runs": mock_runs,
            "candidate_chunks": mock_chunks,
        }[name]

        # Legacy application without candidate_id and resume_versions
        mock_apps.find.return_value = [{
            "_id": "app-legacy-1",
            "candidate_name": "Bob Builder",
            "s3_resume_key": "incoming/bob.pdf",
            "created_at": "2026-01-01T00:00:00Z"
        }]
        mock_runs.find.return_value = []
        mock_chunks.count_documents.return_value = 5

        report = migrate_domain_models(mock_db, dry_run=True)
        assert report["dry_run"] is True
        assert report["applications"]["needs_migration"] == 1
        assert report["applications"]["migrated"] == 0
        mock_apps.update_one.assert_not_called()

    def test_migrate_domain_models_execute_updates_legacy_records(self):
        mock_db = MagicMock()
        mock_apps = MagicMock()
        mock_runs = MagicMock()
        mock_chunks = MagicMock()

        mock_db.__getitem__.side_effect = lambda name: {
            "applications": mock_apps,
            "screening_runs": mock_runs,
            "candidate_chunks": mock_chunks,
        }[name]

        mock_apps.find.return_value = [{
            "_id": "app-legacy-2",
            "candidate_name": "Alice Wonder",
            "s3_resume_key": "incoming/alice.pdf",
            "created_at": "2026-01-01T00:00:00Z"
        }]
        mock_runs.find.return_value = [{
            "_id": "run-legacy-1",
            "job_id": "job-1",
            "tenant_id": "t1"
        }]
        mock_chunks.count_documents.side_effect = [10, 10]
        mock_chunks.update_many.return_value = MagicMock(modified_count=10)

        report = migrate_domain_models(mock_db, dry_run=False)
        assert report["dry_run"] is False
        assert report["applications"]["migrated"] == 1
        assert report["screening_runs"]["migrated"] == 1
        assert report["candidate_chunks"]["migrated"] == 10

        # Verify application update included candidate_id and resume_versions
        mock_apps.update_one.assert_called_once()
        update_payload = mock_apps.update_one.call_args[0][1]["$set"]
        assert update_payload["candidate_id"] == "alice-wonder"
        assert update_payload["current_resume_version"] == 1
        assert len(update_payload["resume_versions"]) == 1
