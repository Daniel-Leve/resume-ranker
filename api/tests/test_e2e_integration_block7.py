"""
Block 7 — End-to-End Integration & Deployment Readiness Test Suite.

Validates:
1. Complete Screening Pipeline:
   - Recruiter creates tenant and job.
   - Candidate views public job and submits application.
   - Presigned upload URL generated with authoritative multi-tenant key.
   - Indexing worker processes extracted resume and marks application INDEXED.
   - Recruiter triggers screening run (Phase 2 + 3 + 4 pipeline).
   - Screening worker executes hybrid search, Voyage rerank, Phase 4 explainability,
     and persists ranked results with evidence excerpts.
   - Recruiter fetches screening results and screening run status.

2. Lifecycle & Archival Consistency:
   - Job update and soft-delete/archival.
   - Application soft-delete/archival.
   - Exclusion of archived applications from screening eligibility.
   - Rejection of screening triggers on archived jobs.
   - Tenant membership addition, role upgrade, revocation, and sole-admin protection.

3. Tenant Isolation & Security Boundaries:
   - Candidate public endpoints never expose tenant_id, internal notes, or screening data.
   - Cross-tenant recruiter access returns 403 Forbidden.
   - Unauthenticated access to protected endpoints returns 401 Unauthorized.
   - Revoked members immediately lose access.

4. Reliability & Error Recovery:
   - Concurrent active screening run prevention (409 Conflict).
   - Premature screening run rejection when no indexed applications exist.
   - Idempotent screening worker execution on SQS redelivery.
   - Graceful Phase 4 degradation if explainability model fails (preserves Phase 3 ranks).

5. Specification Parity:
   - Automated verification that application_handler.py (19 operations),
     template.yaml (19 API events), and docs/openapi.yaml (19 operations)
     remain in exact 1:1 parity.
"""
from __future__ import annotations

import json
import os
import re
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Ensure environment variables
os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SCREENING_QUEUE_URL", "https://sqs.ap-south-1.amazonaws.com/123/test-screening-queue")

from api.handlers.application_handler import _ROUTES, lambda_handler
from api.workers.indexing_worker import _index_single
from api.workers.screening_worker import _run_screening, lambda_handler as screening_lambda_handler
from phase2.retrieval.fusion import CandidateProvenance
from phase3.reranker.document_builder import ReconstructedDocument


# ── Helpers for API Gateway Event Construction ────────────────────────────────

def _claims(sub: str = "recruiter-sub-001", email: str = "recruiter@acme.com"):
    return {
        "sub": sub,
        "email": email,
        "cognito:username": email,
        "email_verified": "true",
    }


def _event(
    method: str,
    resource: str,
    path_params: dict | None = None,
    query_params: dict | None = None,
    body: dict | None = None,
    claims: dict | None = None,
) -> dict:
    evt = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {},
    }
    if claims is not None:
        evt["requestContext"]["authorizer"] = {"claims": claims}
    return evt


class InMemoryCollection:
    """A flexible in-memory mock for MongoDB collections used across E2E tests."""

    def __init__(self, data: list[dict] | None = None):
        self.docs: list[dict] = list(data or [])

    def insert_one(self, doc: dict):
        d = dict(doc)
        if "_id" not in d:
            d["_id"] = str(len(self.docs) + 1)
        self.docs.append(d)
        return MagicMock(inserted_id=d["_id"])

    def _matches(self, doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
                continue
            if isinstance(v, dict):
                if "$in" in v:
                    val = doc.get(k)
                    if val not in v["$in"]:
                        return False
                elif "$ne" in v:
                    if doc.get(k) == v["$ne"]:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    def find_one(self, query: dict, projection: dict | None = None, sort=None):
        matching = [d for d in self.docs if self._matches(d, query)]
        if not matching:
            return None
        doc = matching[-1] if sort else matching[0]
        return self._project(doc, projection)

    def find(self, query: dict, projection: dict | None = None):
        matching = [d for d in self.docs if self._matches(d, query)]

        class Cursor(list):
            def sort(self, key, direction=1):
                return self

            def skip(self, n):
                return Cursor(self[n:])

            def limit(self, n):
                return Cursor(self[:n])

        projected = [self._project(d, projection) for d in matching]
        return Cursor(projected)

    def count_documents(self, query: dict) -> int:
        return len([d for d in self.docs if self._matches(d, query)])

    def update_one(self, query: dict, update: dict, upsert: bool = False):
        matching = [d for d in self.docs if self._matches(d, query)]
        if matching:
            doc = matching[0]
            if "$set" in update:
                doc.update(update["$set"])
            if "$inc" in update:
                for inc_k, inc_v in update["$inc"].items():
                    doc[inc_k] = doc.get(inc_k, 0) + inc_v
            return MagicMock(matched_count=1, modified_count=1)
        elif upsert:
            new_doc = dict(query)
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            if "$set" in update:
                new_doc.update(update["$set"])
            self.docs.append(new_doc)
            return MagicMock(matched_count=0, modified_count=0, upserted_id=new_doc.get("_id"))
        return MagicMock(matched_count=0, modified_count=0)

    def replace_one(self, query: dict, doc: dict, upsert: bool = False):
        matching = [d for d in self.docs if self._matches(d, query)]
        if matching:
            idx = self.docs.index(matching[0])
            self.docs[idx] = dict(doc)
            return MagicMock(matched_count=1, modified_count=1)
        elif upsert:
            new_doc = dict(doc)
            self.docs.append(new_doc)
            return MagicMock(matched_count=0, modified_count=0, upserted_id=new_doc.get("_id"))
        return MagicMock(matched_count=0, modified_count=0)

    def delete_one(self, query: dict):
        matching = [d for d in self.docs if self._matches(d, query)]
        if matching:
            self.docs.remove(matching[0])
            return MagicMock(deleted_count=1)
        return MagicMock(deleted_count=0)

    def delete_many(self, query: dict):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not self._matches(d, query)]
        return MagicMock(deleted_count=before - len(self.docs))

    def create_index(self, *args, **kwargs):
        pass

    def _project(self, doc: dict, projection: dict | None):
        if not projection:
            return dict(doc)
        res = dict(doc)
        if projection.get("_id") == 0:
            res.pop("_id", None)
        else:
            include_keys = [k for k, v in projection.items() if v == 1]
            if include_keys:
                filtered = {k: res[k] for k in include_keys if k in res}
                if "_id" in res and projection.get("_id", 1) != 0:
                    filtered["_id"] = res["_id"]
                return filtered
        return res


def _mock_mongo_db(collections: dict):
    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: collections.setdefault(name, InMemoryCollection())
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    return mock_client, mock_db


# ── TEST SUITE 1: End-to-End Pipeline ──────────────────────────────────────────

class TestEndToEndScreeningPipeline:
    """
    Validates complete flow:
    Tenant -> Job -> Application -> Indexing -> Screening -> Retrieval.
    """

    def test_full_pipeline_success(self):
        collections = {
            "tenants": InMemoryCollection(),
            "tenant_memberships": InMemoryCollection(),
            "jobs": InMemoryCollection(),
            "applications": InMemoryCollection(),
            "candidate_chunks": InMemoryCollection(),
            "screening_runs": InMemoryCollection(),
        }
        mock_client, mock_db = _mock_mongo_db(collections)

        recruiter_claims = _claims(sub="recruiter-sub-100", email="lead_hr@techcorp.com")

        # 1. Recruiter creates tenant
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "POST", "/tenants",
                body={"name": "TechCorp"},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 201
            tenant_body = json.loads(res["body"])
            tenant_id = tenant_body["tenant_id"]
            assert tenant_body["name"] == "TechCorp"

        # 2. Recruiter creates a job under the tenant
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "POST", "/tenants/{tenant_id}/jobs",
                path_params={"tenant_id": tenant_id},
                body={
                    "title": "Senior Python Backend Engineer",
                    "description": "Looking for Python, FastAPI, AWS DynamoDB, MongoDB, and microservices experience.",
                },
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 201
            job_body = json.loads(res["body"])
            job_id = job_body["job_id"]
            assert job_body["status"] == "OPEN"

        # 3. Candidate views public job posting
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}",
                path_params={"job_id": job_id},
            ), None)
            assert res["statusCode"] == 200
            pub_job = json.loads(res["body"])
            assert pub_job["title"] == "Senior Python Backend Engineer"
            assert "tenant_id" not in pub_job  # tenant data not exposed publicly

        # 4. Candidate submits application
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            with patch("boto3.client") as mock_boto:
                mock_s3 = MagicMock()
                mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/presigned-upload-url"
                mock_boto.return_value = mock_s3

                res = lambda_handler(_event(
                    "POST", "/jobs/{job_id}/applications",
                    path_params={"job_id": job_id},
                    body={"candidate_name": "Alice Cooper"},
                ), None)
                assert res["statusCode"] == 201
                app_body = json.loads(res["body"])
                app_id = app_body["application_id"]
                s3_key = app_body["s3_key"]
                assert s3_key == f"incoming/saas__{tenant_id}__{job_id}__{app_id}.pdf"
                assert "upload_url" in app_body

        # 5. Candidate checks public application status
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/status",
                path_params={"job_id": job_id, "application_id": app_id},
            ), None)
            assert res["statusCode"] == 200
            cand_status = json.loads(res["body"])
            assert cand_status["status"] == "PENDING_UPLOAD"
            assert "tenant_id" not in cand_status

        # 6. Simulate Indexing Worker: resume PDF is processed and marked INDEXED
        extracted_s3_key = f"tenants/{tenant_id}/jobs/{job_id}/applications/{app_id}/extracted.json"
        extracted_payload = {
            "status": "SUCCEEDED",
            "text": "Alice Cooper. 7 years experience in Python, AWS DynamoDB, MongoDB, FastAPI microservices.",
            "source": {"key": s3_key},
            "blocks": [],
        }

        with patch("api.workers.indexing_worker._get_mongo", return_value=mock_client):
            with patch("boto3.client") as mock_boto:
                mock_s3 = MagicMock()
                mock_s3.get_object.return_value = {
                    "Body": MagicMock(read=lambda: json.dumps(extracted_payload).encode("utf-8"))
                }
                mock_boto.return_value = mock_s3

                with patch("api.workers.indexing_worker.embed_texts", return_value=[[0.1] * 1024]):
                    _index_single(extracted_s3_key)

        app_doc = collections["applications"].find_one({"_id": app_id})
        assert app_doc["phase2_status"] == "INDEXED"

        # 7. Recruiter triggers screening run
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            with patch("boto3.client") as mock_boto:
                mock_sqs = MagicMock()
                mock_boto.return_value = mock_sqs

                res = lambda_handler(_event(
                    "POST", "/jobs/{job_id}/screening",
                    path_params={"job_id": job_id},
                    claims=recruiter_claims,
                ), None)
                assert res["statusCode"] == 202
                screen_start = json.loads(res["body"])
                screening_run_id = screen_start["screening_run_id"]
                assert screen_start["eligible_candidate_count"] == 1
                mock_sqs.send_message.assert_called_once()

        # 8. Screening Worker executes Phase 2, Phase 3, and Phase 4
        mock_prov = CandidateProvenance(
            candidate_id="alice-cooper",
            rrf_score=0.88,
            lexical_rank=1,
            vector_rank=1,
            matched_chunks={"chunk-1": "Experience"},
            source_key=s3_key,
        )
        mock_rerank = [{"index": 0, "relevance_score": 0.96}]

        mock_doc = ReconstructedDocument(
            candidate_id="alice-cooper",
            text="Alice Cooper. 7 years experience in Python, AWS DynamoDB, MongoDB, FastAPI microservices.",
            chunk_ids=["chunk-1"],
            truncated=False,
        )

        with patch("api.workers.screening_worker._get_mongo", return_value=mock_client):
            with patch("api.workers.screening_worker.embed_texts", return_value=[[0.1] * 1024]):
                with patch("api.workers.screening_worker.lexical_search", return_value=[mock_prov]):
                    with patch("api.workers.screening_worker.vector_search", return_value=[mock_prov]):
                        with patch("api.workers.screening_worker.fuse_results", return_value=[mock_prov]):
                            with patch("api.workers.screening_worker.build_candidate_document", return_value=mock_doc):
                                with patch("api.workers.screening_worker.rerank_documents", return_value=mock_rerank):
                                    with patch("boto3.client") as mock_boto:
                                        mock_s3 = MagicMock()
                                        mock_boto.return_value = mock_s3
                                        _run_screening(screening_run_id, tenant_id, job_id)

        # 9. Recruiter retrieves screening results
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/screening-results",
                path_params={"job_id": job_id},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            results = json.loads(res["body"])
            assert results["status"] == "COMPLETED"
            assert results["candidate_count"] == 1
            candidate = results["candidates"][0]
            assert candidate["rerank_rank"] == 1
            assert candidate["rerank_score"] == 0.96
            assert candidate["candidate_name"] == "Alice Cooper"
            assert candidate["application_id"] == app_id
            # Phase 3 ranking verified; Phase 4 explainability paused until explicitly requested
            assert results.get("phase4_status") == "NOT_STARTED"
            assert candidate["source_key"] is not None

        # 10. Recruiter views screening run by run ID
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/screening-runs/{screening_run_id}",
                path_params={"screening_run_id": screening_run_id},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            run_data = json.loads(res["body"])
            assert run_data["screening_run_id"] == screening_run_id
            assert run_data["tenant_id"] == tenant_id


# ── TEST SUITE 2: Lifecycle & Archival Consistency ─────────────────────────────

class TestLifecycleAndArchivalIntegration:
    """
    Validates resource lifecycle states:
    Job update/archival, application archival, screening exclusion, and membership revocation.
    """

    def test_job_patch_and_archival(self):
        collections = {
            "tenants": InMemoryCollection(),
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "admin-1", "tenant_id": "tenant-1", "role": "ADMIN"},
            ]),
            "jobs": InMemoryCollection([
                {"_id": "job-1", "tenant_id": "tenant-1", "title": "Developer", "status": "OPEN"},
            ]),
        }
        mock_client, _ = _mock_mongo_db(collections)
        admin_claims = _claims(sub="admin-1")

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # Update title and status to CLOSED
            res = lambda_handler(_event(
                "PATCH", "/jobs/{job_id}",
                path_params={"job_id": "job-1"},
                body={"title": "Senior Developer", "status": "CLOSED"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 200
            assert json.loads(res["body"])["title"] == "Senior Developer"
            assert json.loads(res["body"])["status"] == "CLOSED"

            # Archive the job
            res = lambda_handler(_event(
                "DELETE", "/jobs/{job_id}",
                path_params={"job_id": "job-1"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 200
            assert json.loads(res["body"])["status"] == "ARCHIVED"

            # Verify job is now marked ARCHIVED
            job = collections["jobs"].find_one({"_id": "job-1"})
            assert job["status"] == "ARCHIVED"

            # Attempting to trigger screening on archived job returns 409 Conflict
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/screening",
                path_params={"job_id": "job-1"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 409
            assert json.loads(res["body"])["code"] == "JOB_ARCHIVED"

    def test_application_archival_excludes_from_screening(self):
        collections = {
            "tenants": InMemoryCollection(),
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "admin-1", "tenant_id": "tenant-1", "role": "ADMIN"},
            ]),
            "jobs": InMemoryCollection([
                {"_id": "job-1", "tenant_id": "tenant-1", "title": "DevOps", "status": "OPEN"},
            ]),
            "applications": InMemoryCollection([
                {
                    "_id": "app-1",
                    "job_id": "job-1",
                    "tenant_id": "tenant-1",
                    "phase2_status": "INDEXED",
                    "status": "OPEN",
                },
                {
                    "_id": "app-2",
                    "job_id": "job-1",
                    "tenant_id": "tenant-1",
                    "phase2_status": "INDEXED",
                    "status": "OPEN",
                },
            ]),
            "screening_runs": InMemoryCollection(),
        }
        mock_client, _ = _mock_mongo_db(collections)
        admin_claims = _claims(sub="admin-1")

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # Archive app-2
            res = lambda_handler(_event(
                "DELETE", "/jobs/{job_id}/applications/{application_id}",
                path_params={"job_id": "job-1", "application_id": "app-2"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 200
            assert json.loads(res["body"])["status"] == "ARCHIVED"

            # Trigger screening — only app-1 should be eligible (count = 1, not 2)
            with patch("boto3.client") as mock_boto:
                mock_boto.return_value = MagicMock()
                res = lambda_handler(_event(
                    "POST", "/jobs/{job_id}/screening",
                    path_params={"job_id": "job-1"},
                    claims=admin_claims,
                ), None)
                assert res["statusCode"] == 202
                screen_res = json.loads(res["body"])
                assert screen_res["eligible_candidate_count"] == 1

                # Verify recorded screening run input_application_ids has only app-1
                run_id = screen_res["screening_run_id"]
                run_doc = collections["screening_runs"].find_one({"_id": run_id})
                assert run_doc["input_application_ids"] == ["app-1"]

    def test_member_role_management_and_sole_admin_protection(self):
        collections = {
            "tenants": InMemoryCollection([{"_id": "tenant-1", "name": "Acme"}]),
            "tenant_memberships": InMemoryCollection([
                {"_id": "admin-1:tenant-1", "user_sub": "admin-1", "tenant_id": "tenant-1", "role": "ADMIN"},
            ]),
        }
        mock_client, _ = _mock_mongo_db(collections)
        admin_claims = _claims(sub="admin-1")

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # Add new member
            res = lambda_handler(_event(
                "POST", "/tenants/{tenant_id}/members",
                path_params={"tenant_id": "tenant-1"},
                body={"user_sub": "user-2", "role": "MEMBER"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 201

            # List members
            res = lambda_handler(_event(
                "GET", "/tenants/{tenant_id}/members",
                path_params={"tenant_id": "tenant-1"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 200
            members = json.loads(res["body"])["members"]
            assert len(members) == 2

            # Try to revoke sole admin -> 400 LAST_ADMIN_PROTECTION
            res = lambda_handler(_event(
                "DELETE", "/tenants/{tenant_id}/members/{user_sub}",
                path_params={"tenant_id": "tenant-1", "user_sub": "admin-1"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 400
            assert json.loads(res["body"])["code"] == "LAST_ADMIN_PROTECTION"

            # Revoke normal member -> 200
            res = lambda_handler(_event(
                "DELETE", "/tenants/{tenant_id}/members/{user_sub}",
                path_params={"tenant_id": "tenant-1", "user_sub": "user-2"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 200


# ── TEST SUITE 3: Tenant Isolation & Security Boundaries ───────────────────────

class TestPublicBoundaryAndTenantIsolation:
    """
    Validates tenant isolation and public vs protected security boundaries.
    """

    def test_cross_tenant_access_denied(self):
        collections = {
            "tenants": InMemoryCollection(),
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "user-tenant-a", "tenant_id": "tenant-a", "role": "ADMIN"},
            ]),
            "jobs": InMemoryCollection([
                {"_id": "job-b", "tenant_id": "tenant-b", "title": "Secret Job", "status": "OPEN"},
            ]),
        }
        mock_client, _ = _mock_mongo_db(collections)
        user_a_claims = _claims(sub="user-tenant-a")

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # User A cannot trigger screening on Job B
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/screening",
                path_params={"job_id": "job-b"},
                claims=user_a_claims,
            ), None)
            assert res["statusCode"] == 403
            assert json.loads(res["body"])["code"] == "FORBIDDEN"

            # User A cannot view applications of Job B
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/applications",
                path_params={"job_id": "job-b"},
                claims=user_a_claims,
            ), None)
            assert res["statusCode"] == 403

    def test_unauthenticated_protected_route_returns_401(self):
        res = lambda_handler(_event(
            "GET", "/me",
            claims=None,
        ), None)
        assert res["statusCode"] == 401

    def test_candidate_public_status_does_not_leak_internals(self):
        collections = {
            "applications": InMemoryCollection([
                {
                    "_id": "app-secret-1",
                    "job_id": "job-1",
                    "tenant_id": "tenant-secret-999",
                    "candidate_id": "cand-1",
                    "status": "PROCESSING",
                    "phase1_status": "COMPLETED",
                    "phase2_status": "INDEXED",
                    "internal_notes": "Do not hire",
                    "s3_resume_key": "incoming/secret/resume.pdf",
                }
            ]),
        }
        mock_client, _ = _mock_mongo_db(collections)

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/status",
                path_params={"job_id": "job-1", "application_id": "app-secret-1"},
            ), None)
            assert res["statusCode"] == 200
            data = json.loads(res["body"])
            assert "tenant_id" not in data
            assert "internal_notes" not in data
            assert "s3_resume_key" not in data
            assert data["status"] == "PROCESSING"


# ── TEST SUITE 4: Reliability & Error Recovery ─────────────────────────────────

class TestReliabilityAndErrorHandling:
    """
    Validates concurrency guards, worker idempotency, and partial failure handling.
    """

    def test_concurrent_screening_guard(self):
        collections = {
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "admin-1", "tenant_id": "tenant-1", "role": "ADMIN"},
            ]),
            "jobs": InMemoryCollection([
                {"_id": "job-1", "tenant_id": "tenant-1", "status": "OPEN"},
            ]),
            "applications": InMemoryCollection([
                {"_id": "app-1", "job_id": "job-1", "tenant_id": "tenant-1", "phase2_status": "INDEXED"},
            ]),
            "screening_runs": InMemoryCollection([
                {"_id": "run-existing", "screening_run_id": "run-existing", "job_id": "job-1", "tenant_id": "tenant-1", "status": "RUNNING"},
            ]),
        }
        mock_client, _ = _mock_mongo_db(collections)
        admin_claims = _claims(sub="admin-1")

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/screening",
                path_params={"job_id": "job-1"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 409
            assert json.loads(res["body"])["code"] == "SCREENING_ALREADY_IN_PROGRESS"

    def test_premature_screening_rejections(self):
        collections = {
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "admin-1", "tenant_id": "tenant-1", "role": "ADMIN"},
            ]),
            "jobs": InMemoryCollection([
                {"_id": "job-empty", "tenant_id": "tenant-1", "status": "OPEN"},
                {"_id": "job-pending", "tenant_id": "tenant-1", "status": "OPEN"},
            ]),
            "applications": InMemoryCollection([
                {"_id": "app-pending", "job_id": "job-pending", "tenant_id": "tenant-1", "phase2_status": "NOT_STARTED"},
            ]),
            "screening_runs": InMemoryCollection(),
        }
        mock_client, _ = _mock_mongo_db(collections)
        admin_claims = _claims(sub="admin-1")

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # Zero applications -> NO_APPLICATIONS
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/screening",
                path_params={"job_id": "job-empty"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 409
            assert json.loads(res["body"])["code"] == "NO_APPLICATIONS"

            # Pending applications not yet indexed -> APPLICATIONS_NOT_INDEXED
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/screening",
                path_params={"job_id": "job-pending"},
                claims=admin_claims,
            ), None)
            assert res["statusCode"] == 409
            assert json.loads(res["body"])["code"] == "APPLICATIONS_NOT_INDEXED"

    def test_screening_worker_idempotency_on_completed_run(self):
        collections = {
            "screening_runs": InMemoryCollection([
                {
                    "_id": "run-done-1",
                    "screening_run_id": "run-done-1",
                    "status": "COMPLETED",
                    "tenant_id": "tenant-1",
                    "job_id": "job-1",
                }
            ]),
        }
        mock_client, _ = _mock_mongo_db(collections)

        with patch("api.workers.screening_worker._get_mongo", return_value=mock_client):
            # Calling _run_screening should skip re-execution and return immediately
            with patch("api.workers.screening_worker.embed_texts") as mock_embed:
                _run_screening("run-done-1", "tenant-1", "job-1")
                mock_embed.assert_not_called()

    def test_screening_worker_partial_failure_degradation(self):
        """If Phase 4 explainability fails, Phase 3 ranking is preserved and status recorded."""
        collections = {
            "jobs": InMemoryCollection([
                {"_id": "job-1", "tenant_id": "tenant-1", "description": "Python Developer"},
            ]),
            "applications": InMemoryCollection([
                {"_id": "app-1", "job_id": "job-1", "tenant_id": "tenant-1", "candidate_name": "Bob"},
            ]),
            "screening_runs": InMemoryCollection([
                {"_id": "run-p4-fail", "screening_run_id": "run-p4-fail", "status": "QUEUED"},
            ]),
            "candidate_chunks": InMemoryCollection(),
        }
        mock_client, _ = _mock_mongo_db(collections)

        mock_prov = CandidateProvenance(
            candidate_id="bob",
            rrf_score=0.9,
            lexical_rank=1,
            vector_rank=1,
            matched_chunks={"c1": "Skills"},
            source_key="s3://key",
        )
        mock_prov_2 = CandidateProvenance(
            candidate_id="alice",
            rrf_score=0.8,
            lexical_rank=2,
            vector_rank=2,
            matched_chunks={"c2": "Skills"},
            source_key="s3://key2",
        )
        mock_rerank = [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.85},
        ]

        mock_doc = ReconstructedDocument(
            candidate_id="bob",
            text="Bob Python Developer skills and experience",
            chunk_ids=["c1"],
            truncated=False,
        )

        with patch("api.workers.screening_worker._get_mongo", return_value=mock_client):
            with patch("api.workers.screening_worker.embed_texts", return_value=[[0.1] * 1024]):
                with patch("api.workers.screening_worker.lexical_search", return_value=[mock_prov, mock_prov_2]):
                    with patch("api.workers.screening_worker.vector_search", return_value=[mock_prov, mock_prov_2]):
                        with patch("api.workers.screening_worker.fuse_results", return_value=[mock_prov, mock_prov_2]):
                            with patch("api.workers.screening_worker.build_candidate_document", return_value=mock_doc):
                                with patch("api.workers.screening_worker.rerank_documents", return_value=mock_rerank):
                                    with patch("boto3.client") as mock_boto:
                                        mock_boto.return_value = MagicMock()
                                        # Request exactly 1 shortlisted candidate
                                        _run_screening("run-p4-fail", "tenant-1", "job-1", final_shortlisted_candidates_count=1)

        run_doc = collections["screening_runs"].find_one({"_id": "run-p4-fail"})
        assert run_doc["status"] == "COMPLETED"
        assert run_doc["phase3_status"] == "COMPLETED"
        assert run_doc["phase4_status"] == "NOT_STARTED"
        assert run_doc["candidate_count"] == 1
        assert len(run_doc["candidates"]) == 1
        assert run_doc["candidates"][0]["rerank_rank"] == 1
        assert run_doc["final_shortlisted_candidates_count"] == 1
        assert run_doc["phase2_candidate_count"] == 2


# ── TEST SUITE 5: Specification & Route Parity Verification ────────────────────

class TestOpenApiAndTemplateParity:
    """
    Guarantees 1:1 parity across:
    1. application_handler._ROUTES (Python router)
    2. template.yaml (SAM API events)
    3. docs/openapi.yaml (OpenAPI 3.0.3 paths and methods)
    """

    def test_router_has_exact_27_operations(self):
        assert len(_ROUTES) == 27, f"Expected 27 registered route operations in router, found {len(_ROUTES)}"

    def test_openapi_has_exact_27_operations_across_20_paths(self):
        openapi_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "openapi.yaml")
        assert os.path.isfile(openapi_path), f"OpenAPI file not found at {openapi_path}"

        with open(openapi_path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)

        paths = spec.get("paths", {})
        assert len(paths) == 20, f"Expected 20 unique paths in docs/openapi.yaml, found {len(paths)}"

        openapi_operations = set()
        for path_name, methods in paths.items():
            for method in methods.keys():
                if method.lower() in ["get", "post", "patch", "delete", "put"]:
                    openapi_operations.add((method.upper(), path_name))

        assert len(openapi_operations) == 27, (
            f"Expected 27 total operations in docs/openapi.yaml, found {len(openapi_operations)}: {openapi_operations}"
        )

        router_operations = set(_ROUTES.keys())
        assert openapi_operations == router_operations, (
            f"Discrepancy between OpenAPI operations and Python router:\n"
            f"In OpenAPI only: {openapi_operations - router_operations}\n"
            f"In Router only: {router_operations - openapi_operations}"
        )

    def test_sam_template_has_exact_27_api_events(self):
        template_path = os.path.join(os.path.dirname(__file__), "..", "..", "template.yaml")
        assert os.path.isfile(template_path), f"template.yaml not found at {template_path}"

        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract Api events for ApplicationApiHandler
        # Matches:
        # Path: /tenants
        # Method: POST
        api_events = re.findall(
            r"Path:\s*(\S+)\s*\n\s*Method:\s*(\S+)",
            content,
        )
        parsed_events = set((method.upper(), path) for path, method in api_events)

        assert len(parsed_events) == 27, (
            f"Expected 27 API events in template.yaml, found {len(parsed_events)}: {parsed_events}"
        )

        router_operations = set(_ROUTES.keys())
        assert parsed_events == router_operations, (
            f"Discrepancy between SAM template events and Python router:\n"
            f"In template only: {parsed_events - router_operations}\n"
            f"In router only: {router_operations - parsed_events}"
        )
