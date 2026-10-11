"""
Block 3 — Authentication & Tenant Isolation Tests.

Tests covering:
  - Missing, malformed, and valid authentication contexts
  - Authorized and unauthorized tenant access
  - Cross-tenant job, application, and screening-result requests
  - Unauthorized presigned URL generation
  - Public /applications endpoint behaviour
  - Tenant membership enforcement per route
  - Screening and result isolation

Unit tests use mocked Cognito claims and mocked MongoDB collections.
No real AWS resources or network calls are made.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# ── Environment setup before importing handlers ──────────────────────────────
os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SCREENING_QUEUE_URL",
                       "https://sqs.us-east-1.amazonaws.com/123/test-queue")

from api.auth.context import (
    AuthContext,
    extract_auth_context,
    get_user_tenant_membership,
    require_tenant_access,
    TenantMembership,
)
from api.handlers.application_handler import lambda_handler


# ─── Fixtures & Helpers ───────────────────────────────────────────────────────

def _make_claims(sub="user-sub-001", email="hr@acme.com", username="hr@acme.com"):
    return {
        "sub": sub,
        "email": email,
        "cognito:username": username,
        "email_verified": "true",
        "aud": "test-client-id",
        "token_use": "id",
    }


def _make_event(method, resource, path_params=None, body=None, claims=None):
    """Build a minimal API Gateway Lambda proxy event."""
    event = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
        "requestContext": {},
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"claims": claims}
    return event


def _make_db_collections(**mocks):
    """Return a dict of named collection mocks."""
    defaults = {
        "tenants": MagicMock(),
        "jobs": MagicMock(),
        "applications": MagicMock(),
        "screening_runs": MagicMock(),
        "tenant_memberships": MagicMock(),
    }
    defaults.update(mocks)
    return defaults


def _patch_mongo(collections: dict):
    """Context manager that patches _get_mongo to return the given collections."""
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: collections.get(name, MagicMock())
    mock_client.__getitem__.return_value = mock_db
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    return patch("api.handlers.application_handler._get_mongo", return_value=mock_client)


# ─── Unit Tests: extract_auth_context ────────────────────────────────────────

class TestExtractAuthContext:
    def test_valid_claims_returns_auth_context(self):
        event = _make_event("GET", "/test", claims=_make_claims())
        auth = extract_auth_context(event)
        assert auth is not None
        assert auth.user_sub == "user-sub-001"
        assert auth.email == "hr@acme.com"
        assert auth.username == "hr@acme.com"

    def test_no_request_context_returns_none(self):
        event = {"httpMethod": "GET", "resource": "/test"}
        auth = extract_auth_context(event)
        assert auth is None

    def test_empty_authorizer_claims_returns_none(self):
        event = {"requestContext": {"authorizer": {"claims": {}}}}
        auth = extract_auth_context(event)
        assert auth is None

    def test_missing_sub_returns_none(self):
        event = _make_event("GET", "/test", claims={"email": "test@test.com"})
        auth = extract_auth_context(event)
        assert auth is None

    def test_whitespace_only_sub_returns_none(self):
        event = _make_event("GET", "/test", claims={"sub": "   ", "email": "a@b.com"})
        auth = extract_auth_context(event)
        assert auth is None

    def test_no_claims_key_returns_none(self):
        event = {"requestContext": {"authorizer": {}}}
        auth = extract_auth_context(event)
        assert auth is None


# ─── Unit Tests: require_tenant_access ───────────────────────────────────────

class TestRequireTenantAccess:
    def _make_collection(self, doc):
        col = MagicMock()
        col.find_one.return_value = doc
        return col

    def test_admin_passes_admin_requirement(self):
        col = self._make_collection({"tenant_id": "t1", "role": "ADMIN"})
        auth = AuthContext(user_sub="sub-1", email="a@b.com", username="a@b.com")
        result = require_tenant_access(col, auth, "t1", minimum_role="ADMIN")
        assert result is not None
        assert result.role == "ADMIN"

    def test_admin_passes_member_requirement(self):
        col = self._make_collection({"tenant_id": "t1", "role": "ADMIN"})
        auth = AuthContext(user_sub="sub-1", email="a@b.com", username="a@b.com")
        result = require_tenant_access(col, auth, "t1", minimum_role="MEMBER")
        assert result is not None

    def test_member_fails_admin_requirement(self):
        col = self._make_collection({"tenant_id": "t1", "role": "MEMBER"})
        auth = AuthContext(user_sub="sub-1", email="a@b.com", username="a@b.com")
        result = require_tenant_access(col, auth, "t1", minimum_role="ADMIN")
        assert result is None

    def test_no_membership_returns_none(self):
        col = self._make_collection(None)
        auth = AuthContext(user_sub="sub-nobody", email="a@b.com", username="a@b.com")
        result = require_tenant_access(col, auth, "t-other", minimum_role="MEMBER")
        assert result is None

    def test_membership_scoped_to_correct_tenant(self):
        col = MagicMock()
        col.find_one.return_value = None  # wrong tenant → not found
        auth = AuthContext(user_sub="sub-1", email="a@b.com", username="a@b.com")
        result = require_tenant_access(col, auth, "t-OTHER", minimum_role="MEMBER")
        assert result is None
        # Verify query used tenant_id from parameter, not from somewhere else
        col.find_one.assert_called_once_with(
            {"user_sub": "sub-1", "tenant_id": "t-OTHER"},
            {"tenant_id": 1, "role": 1, "_id": 0},
        )


# ─── Integration Tests: POST /tenants ────────────────────────────────────────

class TestPostTenants:
    def test_requires_auth(self):
        """No JWT claims → 401."""
        event = _make_event("POST", "/tenants", body={"name": "Acme Corp"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_creates_tenant_and_membership(self):
        """Authenticated user → tenant created + ADMIN membership."""
        cols = _make_db_collections()
        event = _make_event(
            "POST", "/tenants",
            body={"name": "Acme Corp"},
            claims=_make_claims(sub="user-abc"),
        )
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert "tenant_id" in body
        assert body["role"] == "ADMIN"

        # Verify membership was inserted
        cols["tenant_memberships"].insert_one.assert_called_once()
        mem_doc = cols["tenant_memberships"].insert_one.call_args[0][0]
        assert mem_doc["user_sub"] == "user-abc"
        assert mem_doc["role"] == "ADMIN"
        assert mem_doc["tenant_id"] == body["tenant_id"]

    def test_missing_name_returns_400(self):
        event = _make_event("POST", "/tenants", body={}, claims=_make_claims())
        cols = _make_db_collections()
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400


# ─── Integration Tests: POST /tenants/{tenant_id}/jobs ───────────────────────

class TestPostJobs:
    def test_requires_auth(self):
        event = _make_event("POST", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t1"},
                            body={"title": "Engineer"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_member_cannot_create_job(self):
        """MEMBER role is insufficient — ADMIN required."""
        cols = _make_db_collections()
        cols["tenant_memberships"].find_one.return_value = {"tenant_id": "t1", "role": "MEMBER"}
        event = _make_event("POST", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t1"},
                            body={"title": "Eng"},
                            claims=_make_claims())
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403
        assert json.loads(resp["body"])["code"] == "FORBIDDEN"

    def test_admin_creates_job(self):
        """ADMIN role can create a job."""
        cols = _make_db_collections()
        cols["tenant_memberships"].find_one.return_value = {"tenant_id": "t1", "role": "ADMIN"}
        event = _make_event("POST", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t1"},
                            body={"title": "Backend Eng", "description": "Python dev"},
                            claims=_make_claims())
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["tenant_id"] == "t1"
        assert "job_id" in body

    def test_cross_tenant_blocked(self):
        """User with no membership in t-other → 403."""
        cols = _make_db_collections()
        cols["tenant_memberships"].find_one.return_value = None  # no membership
        event = _make_event("POST", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t-other"},
                            body={"title": "Eng"},
                            claims=_make_claims(sub="hacker-sub"))
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


# ─── Integration Tests: POST /jobs/{job_id}/applications (PUBLIC) ────────────

class TestPostApplicationPublic:
    def test_no_auth_allowed_for_public_endpoint(self):
        """Applications endpoint is public — no JWT required."""
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {
            "_id": "job-1", "tenant_id": "t1", "status": "OPEN"
        }
        event = _make_event("POST", "/jobs/{job_id}/applications",
                            path_params={"job_id": "job-1"},
                            body={"candidate_name": "Jane Doe"})
        # No claims in event
        with _patch_mongo(cols), \
             patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_url.return_value = "https://s3.presigned.url/test"
            mock_boto.return_value = mock_s3
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert "upload_url" in body
        assert "application_id" in body

    def test_tenant_id_derived_from_db_not_caller(self):
        """The tenant_id used for the S3 key must come from the DB job lookup."""
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {
            "_id": "job-1", "tenant_id": "real-tenant-from-db", "status": "OPEN"
        }
        event = _make_event("POST", "/jobs/{job_id}/applications",
                            path_params={"job_id": "job-1"},
                            body={"candidate_name": "Jane Doe"})
        with _patch_mongo(cols), \
             patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_url.return_value = "https://s3.presigned.url/test"
            mock_boto.return_value = mock_s3
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        # The s3_key must contain the real tenant from DB, not anything caller-supplied
        assert "real-tenant-from-db" in body["s3_key"]

    def test_closed_job_returns_409(self):
        """A closed job should reject new applications."""
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {
            "_id": "job-1", "tenant_id": "t1", "status": "CLOSED"
        }
        event = _make_event("POST", "/jobs/{job_id}/applications",
                            path_params={"job_id": "job-1"},
                            body={"candidate_name": "Jane"})
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 409
        assert json.loads(resp["body"])["code"] == "JOB_CLOSED"

    def test_nonexistent_job_returns_404(self):
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = None
        event = _make_event("POST", "/jobs/{job_id}/applications",
                            path_params={"job_id": "no-such-job"},
                            body={"candidate_name": "Jane"})
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 404


# ─── Integration Tests: POST /jobs/{job_id}/screening ────────────────────────

class TestPostScreeningAuth:
    def test_requires_auth(self):
        event = _make_event("POST", "/jobs/{job_id}/screening",
                            path_params={"job_id": "job-1"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_non_member_cannot_trigger_screening(self):
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {"_id": "job-1", "tenant_id": "t1"}
        cols["tenant_memberships"].find_one.return_value = None
        event = _make_event("POST", "/jobs/{job_id}/screening",
                            path_params={"job_id": "job-1"},
                            claims=_make_claims(sub="attacker-sub"))
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403

    def test_member_cannot_trigger_screening_admin_required(self):
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {"_id": "job-1", "tenant_id": "t1"}
        cols["tenant_memberships"].find_one.return_value = {
            "tenant_id": "t1", "role": "MEMBER"
        }
        event = _make_event("POST", "/jobs/{job_id}/screening",
                            path_params={"job_id": "job-1"},
                            claims=_make_claims())
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403

    def test_admin_can_trigger_screening_when_indexed_apps_exist(self):
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {"_id": "job-1", "tenant_id": "t1"}
        cols["tenant_memberships"].find_one.return_value = {
            "tenant_id": "t1", "role": "ADMIN"
        }
        cols["screening_runs"].find_one.return_value = None
        cols["applications"].count_documents.return_value = 3  # indexed apps

        event = _make_event("POST", "/jobs/{job_id}/screening",
                            path_params={"job_id": "job-1"},
                            claims=_make_claims(sub="admin-sub"))
        with _patch_mongo(cols), \
             patch("boto3.client") as mock_boto:
            mock_sqs = MagicMock()
            mock_boto.return_value = mock_sqs
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 202
        body = json.loads(resp["body"])
        assert body["eligible_candidate_count"] == 3

        # Screening run must record who initiated it
        insert_call = cols["screening_runs"].insert_one.call_args[0][0]
        assert insert_call["initiated_by_sub"] == "admin-sub"
        assert insert_call["tenant_id"] == "t1"


# ─── Integration Tests: GET /jobs/{job_id}/screening-results ─────────────────

class TestGetScreeningResultsAuth:
    def test_requires_auth(self):
        event = _make_event("GET", "/jobs/{job_id}/screening-results",
                            path_params={"job_id": "job-1"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_cross_tenant_cannot_see_results(self):
        """A user with membership in t1 cannot see results for a job in t2."""
        cols = _make_db_collections()
        # job-99 belongs to t2
        cols["jobs"].find_one.return_value = {"_id": "job-99", "tenant_id": "t2"}
        # This user is not a member of t2 (belongs to t1 only)
        cols["tenant_memberships"].find_one.return_value = None

        event = _make_event("GET", "/jobs/{job_id}/screening-results",
                            path_params={"job_id": "job-99"},
                            claims=_make_claims(sub="t1-user"))
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403

    def test_member_can_see_own_tenant_results(self):
        """MEMBER of the job's tenant can view results."""
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {"_id": "job-1", "tenant_id": "t1"}
        cols["tenant_memberships"].find_one.return_value = {
            "tenant_id": "t1", "role": "MEMBER"
        }
        cols["screening_runs"].find_one.return_value = {
            "job_id": "job-1",
            "tenant_id": "t1",
            "status": "COMPLETED",
            "candidates": [{"candidate_id": "cand-x", "rerank_rank": 1}],
        }
        event = _make_event("GET", "/jobs/{job_id}/screening-results",
                            path_params={"job_id": "job-1"},
                            claims=_make_claims())
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "COMPLETED"
        assert body["tenant_id"] == "t1"

    def test_results_query_scoped_by_tenant(self):
        """Verify the MongoDB query for results always includes tenant_id."""
        cols = _make_db_collections()
        cols["jobs"].find_one.return_value = {"_id": "job-1", "tenant_id": "t1"}
        cols["tenant_memberships"].find_one.return_value = {
            "tenant_id": "t1", "role": "MEMBER"
        }
        cols["screening_runs"].find_one.return_value = {
            "job_id": "job-1", "tenant_id": "t1", "status": "QUEUED", "candidates": []
        }
        event = _make_event("GET", "/jobs/{job_id}/screening-results",
                            path_params={"job_id": "job-1"},
                            claims=_make_claims())
        with _patch_mongo(cols):
            lambda_handler(event, None)

        # Verify the query to screening_runs includes tenant_id scoping
        find_call = cols["screening_runs"].find_one.call_args[0][0]
        assert find_call["tenant_id"] == "t1"
        assert find_call["job_id"] == "job-1"


# ─── Integration Tests: GET /tenants/{tenant_id}/jobs ────────────────────────

class TestGetJobsAuth:
    def test_requires_auth(self):
        event = _make_event("GET", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t1"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_non_member_cannot_list_jobs(self):
        cols = _make_db_collections()
        cols["tenant_memberships"].find_one.return_value = None
        event = _make_event("GET", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t1"},
                            claims=_make_claims(sub="outsider"))
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403

    def test_member_can_list_jobs(self):
        cols = _make_db_collections()
        cols["tenant_memberships"].find_one.return_value = {
            "tenant_id": "t1", "role": "MEMBER"
        }
        cols["tenants"].find_one.return_value = {"_id": "t1", "name": "Acme"}
        cols["jobs"].find.return_value = [
            {"job_id": "j1", "title": "Engineer", "tenant_id": "t1"}
        ]
        event = _make_event("GET", "/tenants/{tenant_id}/jobs",
                            path_params={"tenant_id": "t1"},
                            claims=_make_claims())
        with _patch_mongo(cols):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        assert len(json.loads(resp["body"])["jobs"]) == 1


# ─── Regression: Block 1 & 2 routes still work ───────────────────────────────

class TestBlock1Block2Regression:
    def test_unknown_route_returns_404(self):
        event = _make_event("DELETE", "/tenants", claims=_make_claims())
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 404

    def test_lambda_handler_catches_unhandled_exceptions(self):
        """Global exception handler must return 500, not raise."""
        event = _make_event("POST", "/tenants", claims=_make_claims(),
                            body={"name": "Boom"})
        with patch("api.handlers.application_handler._get_mongo",
                   side_effect=Exception("DB exploded")):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 500
