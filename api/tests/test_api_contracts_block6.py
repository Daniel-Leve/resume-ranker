"""
Block 6 — API Contract & Frontend Readiness Tests.

Tests covering:
  - Recruiter workspace: GET /me, PATCH /jobs/{job_id}, GET /jobs/{job_id}/applications,
    GET /jobs/{job_id}/applications/{application_id}, GET /screening-runs/{screening_run_id},
    GET & POST /tenants/{tenant_id}/members.
  - Candidate portal: GET /jobs/{job_id}, GET /jobs/{job_id}/applications/{application_id}/status.
  - Role enforcement (ADMIN vs MEMBER) and tenant isolation.
  - Public boundary validation (ensuring candidate endpoints don't leak tenant or internal data).
  - Screening results response schema with Phase 4 explanations.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# ── Environment setup before importing handlers ──────────────────────────────
os.environ.setdefault("S3_BUCKET_NAME", "test-screening-bucket")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SCREENING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/test-queue")

from api.handlers.application_handler import lambda_handler


def _make_claims(sub="user-sub-001", email="hr@acme.com", username="hr@acme.com"):
    return {
        "sub": sub,
        "email": email,
        "cognito:username": username,
        "email_verified": "true",
    }


def _make_event(method, resource, path_params=None, query_params=None, body=None, claims=None):
    event = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {},
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"claims": claims}
    return event


def _patch_mongo(collections: dict):
    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: collections.get(name, MagicMock())
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    return patch("api.handlers.application_handler._get_mongo", return_value=mock_client)


# ─── 1. GET /me (Recruiter Identity & Memberships) ──────────────────────────

def test_get_me_unauthenticated():
    event = _make_event("GET", "/me")
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 401
    assert "Authentication required" in json.loads(resp["body"])["error"]


def test_get_me_success():
    claims = _make_claims("sub_123", "recruiter@corp.com")
    cols = {
        "tenant_memberships": MagicMock(),
        "tenants": MagicMock(),
    }
    cols["tenant_memberships"].find.return_value = [
        {"user_sub": "sub_123", "tenant_id": "tenant_1", "role": "ADMIN"},
        {"user_sub": "sub_123", "tenant_id": "tenant_2", "role": "MEMBER"},
    ]
    cols["tenants"].find_one.side_effect = [
        {"_id": "tenant_1", "name": "Corp One", "status": "ACTIVE"},
        {"_id": "tenant_2", "name": "Corp Two", "status": "ACTIVE"},
    ]

    event = _make_event("GET", "/me", claims=claims)
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["user_sub"] == "sub_123"
    assert body["email"] == "recruiter@corp.com"
    assert len(body["tenants"]) == 2
    assert body["tenants"][0]["tenant_id"] == "tenant_1"
    assert body["tenants"][0]["name"] == "Corp One"
    assert body["tenants"][0]["role"] == "ADMIN"
    assert body["tenants"][1]["role"] == "MEMBER"


# ─── 2. Candidate Portal: GET /jobs/{job_id} (Public) ───────────────────────

def test_get_public_job_success():
    cols = {"jobs": MagicMock()}
    cols["jobs"].find_one.return_value = {
        "_id": "job_101",
        "job_id": "job_101",
        "tenant_id": "secret_tenant_xyz",
        "title": "Senior Backend Engineer",
        "description": "Build high scale microservices.",
        "status": "OPEN",
        "created_at": "2026-10-01T00:00:00Z",
        "application_count": 42,
    }

    event = _make_event("GET", "/jobs/{job_id}", path_params={"job_id": "job_101"})
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["job_id"] == "job_101"
    assert body["title"] == "Senior Backend Engineer"
    assert body["status"] == "OPEN"
    # Ensure tenant_id and application_count are stripped / not leaked
    assert "tenant_id" not in body
    assert "application_count" not in body


def test_get_public_job_not_found():
    cols = {"jobs": MagicMock()}
    cols["jobs"].find_one.return_value = None

    event = _make_event("GET", "/jobs/{job_id}", path_params={"job_id": "job_nonexistent"})
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 404


# ─── 3. PATCH /jobs/{job_id} (Recruiter Update Job) ─────────────────────────

def test_patch_job_requires_admin_role():
    claims = _make_claims("sub_member")
    cols = {
        "jobs": MagicMock(),
        "tenant_memberships": MagicMock(),
    }
    cols["jobs"].find_one.side_effect = [
        {"_id": "job_01", "tenant_id": "tenant_alpha"},  # _resolve_job_tenant
    ]
    # Caller is only MEMBER, but ADMIN is required to PATCH
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": "sub_member",
        "tenant_id": "tenant_alpha",
        "role": "MEMBER",
    }

    event = _make_event(
        "PATCH",
        "/jobs/{job_id}",
        path_params={"job_id": "job_01"},
        body={"status": "CLOSED"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 403
    assert "admin access" in json.loads(resp["body"])["error"]


def test_patch_job_success():
    claims = _make_claims("sub_admin")
    cols = {
        "jobs": MagicMock(),
        "tenant_memberships": MagicMock(),
    }
    cols["jobs"].find_one.side_effect = [
        {"_id": "job_01", "tenant_id": "tenant_alpha"},  # _resolve_job_tenant
        {
            "_id": "job_01",
            "job_id": "job_01",
            "tenant_id": "tenant_alpha",
            "title": "Updated Title",
            "status": "CLOSED",
        },
    ]
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": "sub_admin",
        "tenant_id": "tenant_alpha",
        "role": "ADMIN",
    }

    event = _make_event(
        "PATCH",
        "/jobs/{job_id}",
        path_params={"job_id": "job_01"},
        body={"title": "Updated Title", "status": "CLOSED"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["title"] == "Updated Title"
    assert body["status"] == "CLOSED"
    cols["jobs"].update_one.assert_called_once()


# ─── 4. Applications Listing & Detail (Recruiter) ───────────────────────────

def test_get_applications_with_pagination():
    claims = _make_claims()
    cols = {
        "jobs": MagicMock(),
        "tenant_memberships": MagicMock(),
        "applications": MagicMock(),
    }
    cols["jobs"].find_one.return_value = {"_id": "job_01", "tenant_id": "tenant_alpha"}
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": claims["sub"], "tenant_id": "tenant_alpha", "role": "MEMBER"
    }
    cols["applications"].count_documents.return_value = 15
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.limit.return_value = [
        {"application_id": "app_1", "candidate_name": "Alice", "status": "INDEXED"},
        {"application_id": "app_2", "candidate_name": "Bob", "status": "PENDING_UPLOAD"},
    ]
    cols["applications"].find.return_value = mock_cursor

    event = _make_event(
        "GET",
        "/jobs/{job_id}/applications",
        path_params={"job_id": "job_01"},
        query_params={"limit": "2", "skip": "0"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["total"] == 15
    assert body["limit"] == 2
    assert body["skip"] == 0
    assert len(body["applications"]) == 2


def test_get_application_detail():
    claims = _make_claims()
    cols = {
        "jobs": MagicMock(),
        "tenant_memberships": MagicMock(),
        "applications": MagicMock(),
    }
    cols["jobs"].find_one.return_value = {"_id": "job_01", "tenant_id": "tenant_alpha"}
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": claims["sub"], "tenant_id": "tenant_alpha", "role": "MEMBER"
    }
    cols["applications"].find_one.return_value = {
        "application_id": "app_100",
        "job_id": "job_01",
        "tenant_id": "tenant_alpha",
        "candidate_name": "Alice",
        "current_resume_version": 1,
        "phase2_status": "INDEXED",
    }

    event = _make_event(
        "GET",
        "/jobs/{job_id}/applications/{application_id}",
        path_params={"job_id": "job_01", "application_id": "app_100"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["application_id"] == "app_100"


# ─── 5. Candidate Application Status (Public) ───────────────────────────────

def test_get_candidate_application_status_public():
    cols = {"applications": MagicMock()}
    cols["applications"].find_one.return_value = {
        "_id": "app_100",
        "job_id": "job_01",
        "tenant_id": "secret_tenant",
        "candidate_name": "Candidate X",
        "status": "PROCESSING",
        "phase1_status": "SUCCEEDED",
        "phase2_status": "INDEXING",
        "created_at": "2026-10-02T10:00:00Z",
    }

    event = _make_event(
        "GET",
        "/jobs/{job_id}/applications/{application_id}/status",
        path_params={"job_id": "job_01", "application_id": "app_100"},
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["application_id"] == "app_100"
    assert body["status"] == "PROCESSING"
    assert body["phase2_status"] == "INDEXING"
    # Never leak tenant_id
    assert "tenant_id" not in body


# ─── 6. Screening Run by ID & Results (Protected) ───────────────────────────

def test_get_screening_run_by_id_tenant_isolated():
    claims = _make_claims("sub_intruder")
    cols = {
        "screening_runs": MagicMock(),
        "tenant_memberships": MagicMock(),
    }
    cols["screening_runs"].find_one.return_value = {
        "screening_run_id": "run_999",
        "tenant_id": "tenant_other",
        "status": "COMPLETED",
    }
    # Intruder has no membership in tenant_other
    cols["tenant_memberships"].find_one.return_value = None

    event = _make_event(
        "GET",
        "/screening-runs/{screening_run_id}",
        path_params={"screening_run_id": "run_999"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 403


def test_get_screening_results_includes_phase4_explanations():
    claims = _make_claims()
    cols = {
        "jobs": MagicMock(),
        "tenant_memberships": MagicMock(),
        "screening_runs": MagicMock(),
    }
    cols["jobs"].find_one.return_value = {"_id": "job_01", "tenant_id": "tenant_alpha"}
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": claims["sub"], "tenant_id": "tenant_alpha", "role": "MEMBER"
    }

    sample_run = {
        "screening_run_id": "run_888",
        "job_id": "job_01",
        "tenant_id": "tenant_alpha",
        "status": "COMPLETED",
        "phase2_status": "COMPLETED",
        "phase3_status": "COMPLETED",
        "phase4_status": "COMPLETED",
        "candidates": [
            {
                "candidate_id": "cand_01",
                "application_id": "app_01",
                "rerank_rank": 1,
                "rerank_score": 0.942,
                "rank_change": 0,
                "phase2": {
                    "hybrid_score": 0.082,
                    "matched_chunks": [{"chunk_id": "c1", "section": "experience"}],
                },
                "explanation": {
                    "candidate_id": "cand_01",
                    "rerank_rank": 1,
                    "summary": "Ranked #1 by semantic reranking.",
                    "matched_sections": ["experience"],
                    "supporting_evidence": [
                        {"chunk_id": "c1", "section": "experience", "excerpt": "Python engineer"}
                    ],
                    "requirement_alignment": [
                        {"requirement": "Python skills", "status": "supported", "supporting_chunks": ["c1"]}
                    ],
                    "evidence_gaps": [],
                    "limitations": ["Audit disclaimer."],
                    "explanation_version": "1.0.0",
                },
            }
        ],
    }
    cols["screening_runs"].find_one.return_value = sample_run

    event = _make_event(
        "GET",
        "/jobs/{job_id}/screening-results",
        path_params={"job_id": "job_01"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["phase4_status"] == "COMPLETED"
    candidate = body["candidates"][0]
    assert candidate["rerank_rank"] == 1
    assert "explanation" in candidate
    assert candidate["explanation"]["explanation_version"] == "1.0.0"


# ─── 7. Tenant Memberships Management ───────────────────────────────────────

def test_tenant_members_management():
    admin_claims = _make_claims("sub_admin")
    cols = {
        "tenant_memberships": MagicMock(),
    }
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": "sub_admin", "tenant_id": "tenant_alpha", "role": "ADMIN"
    }
    cols["tenant_memberships"].find.return_value = [
        {"user_sub": "sub_admin", "tenant_id": "tenant_alpha", "role": "ADMIN"},
        {"user_sub": "sub_colleague", "tenant_id": "tenant_alpha", "role": "MEMBER"},
    ]

    # 1. GET /tenants/{tenant_id}/members
    get_event = _make_event(
        "GET",
        "/tenants/{tenant_id}/members",
        path_params={"tenant_id": "tenant_alpha"},
        claims=admin_claims,
    )
    with _patch_mongo(cols):
        get_resp = lambda_handler(get_event, None)

    assert get_resp["statusCode"] == 200
    assert len(json.loads(get_resp["body"])["members"]) == 2

    # 2. POST /tenants/{tenant_id}/members
    post_event = _make_event(
        "POST",
        "/tenants/{tenant_id}/members",
        path_params={"tenant_id": "tenant_alpha"},
        body={"user_sub": "sub_new_user", "role": "MEMBER"},
        claims=admin_claims,
    )
    with _patch_mongo(cols):
        post_resp = lambda_handler(post_event, None)

    assert post_resp["statusCode"] == 201
    assert json.loads(post_resp["body"])["role"] == "MEMBER"
    cols["tenant_memberships"].update_one.assert_called_once()


# ─── 8. Lifecycle & Deletion Operations ──────────────────────────────────────

def test_delete_job_archives_job():
    claims = _make_claims("sub_admin")
    cols = {
        "jobs": MagicMock(),
        "tenant_memberships": MagicMock(),
    }
    cols["jobs"].find_one.return_value = {"_id": "job_01", "tenant_id": "tenant_alpha"}
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": "sub_admin", "tenant_id": "tenant_alpha", "role": "ADMIN"
    }

    event = _make_event(
        "DELETE",
        "/jobs/{job_id}",
        path_params={"job_id": "job_01"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ARCHIVED"
    cols["jobs"].update_one.assert_called_once()


def test_delete_application_archives_application():
    claims = _make_claims("sub_member")
    cols = {
        "jobs": MagicMock(),
        "applications": MagicMock(),
        "tenant_memberships": MagicMock(),
    }
    cols["jobs"].find_one.return_value = {"_id": "job_01", "tenant_id": "tenant_alpha"}
    cols["tenant_memberships"].find_one.return_value = {
        "user_sub": "sub_member", "tenant_id": "tenant_alpha", "role": "MEMBER"
    }
    mock_update_res = MagicMock()
    mock_update_res.matched_count = 1
    cols["applications"].update_one.return_value = mock_update_res

    event = _make_event(
        "DELETE",
        "/jobs/{job_id}/applications/{application_id}",
        path_params={"job_id": "job_01", "application_id": "app_01"},
        claims=claims,
    )
    with _patch_mongo(cols):
        resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ARCHIVED"


def test_delete_tenant_member_revocation_and_sole_admin_protection():
    admin_claims = _make_claims("sub_admin_1")
    cols = {
        "tenant_memberships": MagicMock(),
    }
    # Caller is admin
    cols["tenant_memberships"].find_one.side_effect = [
        {"user_sub": "sub_admin_1", "tenant_id": "tenant_alpha", "role": "ADMIN"},  # require_tenant_access
        {"user_sub": "sub_admin_1", "tenant_id": "tenant_alpha", "role": "ADMIN"},  # target is admin_1
    ]
    # Sole admin check: only 1 admin
    cols["tenant_memberships"].count_documents.return_value = 1

    # 1. Attempt to revoke sole admin -> 400 Bad Request
    fail_event = _make_event(
        "DELETE",
        "/tenants/{tenant_id}/members/{user_sub}",
        path_params={"tenant_id": "tenant_alpha", "user_sub": "sub_admin_1"},
        claims=admin_claims,
    )
    with _patch_mongo(cols):
        fail_resp = lambda_handler(fail_event, None)

    assert fail_resp["statusCode"] == 400
    assert "sole administrator" in json.loads(fail_resp["body"])["error"]

    # 2. Successfully revoke non-admin member
    cols["tenant_memberships"].find_one.side_effect = [
        {"user_sub": "sub_admin_1", "tenant_id": "tenant_alpha", "role": "ADMIN"},
        {"user_sub": "sub_member_2", "tenant_id": "tenant_alpha", "role": "MEMBER"},
    ]
    success_event = _make_event(
        "DELETE",
        "/tenants/{tenant_id}/members/{user_sub}",
        path_params={"tenant_id": "tenant_alpha", "user_sub": "sub_member_2"},
        claims=admin_claims,
    )
    with _patch_mongo(cols):
        success_resp = lambda_handler(success_event, None)

    assert success_resp["statusCode"] == 200
    assert json.loads(success_resp["body"])["message"] == "Membership revoked successfully."
    cols["tenant_memberships"].delete_one.assert_called_once_with({
        "user_sub": "sub_member_2", "tenant_id": "tenant_alpha"
    })
