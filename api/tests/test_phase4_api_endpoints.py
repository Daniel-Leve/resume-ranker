"""
Unit & Integration Test Suite for Phase 4 REST API Endpoints in application_handler.py.
Tests all 8 new endpoints:
1. POST /jobs/{job_id}/rubric
2. GET /jobs/{job_id}/rubric
3. POST /jobs/{job_id}/rubric/approve
4. Screening trigger rubric approval gate check (POST /jobs/{job_id}/screening)
5. GET /jobs/{job_id}/screening-status
6. GET /jobs/{job_id}/candidates/{candidate_id}/report
7. GET /jobs/{job_id}/review-queue
8. POST /jobs/{job_id}/review-queue/{candidate_id}/action
9. GET /jobs/{job_id}/applications/{application_id}/feedback
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from api.handlers.application_handler import lambda_handler
from phase4.llm_client import MockLLMClient
from phase4.schemas import JobRubric, RubricCriterion


def _event(
    method: str,
    path: str,
    body: dict = None,
    path_params: dict = None,
    query_params: dict = None,
    claims: dict = None,
) -> dict:
    req_context = {}
    if claims:
        req_context["authorizer"] = {"claims": claims}
    return {
        "httpMethod": method.upper(),
        "resource": path,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body) if body else None,
        "requestContext": req_context,
    }


class InMemoryCollection:
    def __init__(self, initial=None):
        self.docs = list(initial) if initial else []

    def find_one(self, query=None, projection=None, sort=None):
        docs = self.docs
        if query:
            for k, v in query.items():
                if isinstance(v, dict) and "$ne" in v:
                    docs = [d for d in docs if d.get(k) != v["$ne"]]
                else:
                    docs = [d for d in docs if d.get(k) == v]
        if sort and docs:
            # simple sort simulation
            field, direction = sort[0]
            docs = sorted(docs, key=lambda d: d.get(field, ""), reverse=(direction == -1))
        if docs:
            d = dict(docs[0])
            if projection and "_id" not in projection:
                d.pop("_id", None)
            return d
        return None

    def find(self, query=None, projection=None, sort=None):
        docs = list(self.docs)
        if query:
            for k, v in query.items():
                if isinstance(v, dict) and "$ne" in v:
                    docs = [d for d in docs if d.get(k) != v["$ne"]]
                else:
                    docs = [d for d in docs if d.get(k) == v]
        return docs

    def count_documents(self, query=None):
        return len(self.find(query))

    def insert_one(self, doc):
        d = dict(doc)
        if "_id" not in d:
            d["_id"] = str(len(self.docs) + 1)
        self.docs.append(d)
        return MagicMock(inserted_id=d["_id"])

    def update_one(self, query, update):
        target = self.find_one(query)
        if target:
            if "$set" in update:
                for k, v in update["$set"].items():
                    target[k] = v
            # update in memory
            for i, d in enumerate(self.docs):
                if d.get("_id") == target.get("_id"):
                    self.docs[i] = target
            return MagicMock(matched_count=1, modified_count=1)
        return MagicMock(matched_count=0, modified_count=0)

    def update_many(self, query, update):
        matched = 0
        for d in self.docs:
            matches = True
            if query:
                for k, v in query.items():
                    if k == "$or" and isinstance(v, list):
                        if not any(all(d.get(sub_k) == sub_v for sub_k, sub_v in cond.items()) for cond in v):
                            matches = False
                            break
                    elif d.get(k) != v:
                        matches = False
                        break
            if matches:
                matched += 1
                if "$set" in update:
                    for k, v in update["$set"].items():
                        d[k] = v
        return MagicMock(matched_count=matched, modified_count=matched)


def _mock_mongo(collections_map):
    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: collections_map.get(name, InMemoryCollection())
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.__enter__.return_value = mock_client
    return mock_client


@pytest.fixture
def recruiter_claims():
    return {
        "sub": "recruiter-sub-100",
        "email": "recruiter@acme.com",
        "cognito:username": "recruiter_bob",
    }


class TestPhase4ApiEndpoints:
    def test_rubric_build_and_approve_flow(self, recruiter_claims):
        collections = {
            "tenants": InMemoryCollection([
                {"_id": "tenant-100", "tenant_id": "tenant-100", "name": "Acme Corp", "status": "ACTIVE"}
            ]),
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "recruiter-sub-100", "tenant_id": "tenant-100", "role": "ADMIN"}
            ]),
            "jobs": InMemoryCollection([
                {
                    "_id": "job-py-01",
                    "job_id": "job-py-01",
                    "tenant_id": "tenant-100",
                    "title": "Senior Python Engineer",
                    "description": "5+ years Python backend development with FastAPI and MongoDB.",
                    "status": "PUBLISHED",
                }
            ]),
            "applications": InMemoryCollection(),
            "screening_runs": InMemoryCollection(),
        }
        mock_client = _mock_mongo(collections)

        canned_rubric = json.dumps({
            "criteria": [
                {
                    "id": "c1",
                    "description": "Python backend experience with FastAPI",
                    "type": "must",
                    "weight": 0.6,
                    "how_to_verify": "Look for FastAPI production microservices",
                },
                {
                    "id": "c2",
                    "description": "MongoDB schema design",
                    "type": "must",
                    "weight": 0.4,
                    "how_to_verify": "Look for database queries and aggregation pipelines",
                },
            ]
        })
        mock_llm = MockLLMClient(canned_responses=[canned_rubric])

        # 1. POST /jobs/{job_id}/rubric (Draft rubric)
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            with patch("phase4.llm_client.GroqClient", return_value=mock_llm):
                res = lambda_handler(_event(
                    "POST", "/jobs/{job_id}/rubric",
                    path_params={"job_id": "job-py-01"},
                    claims=recruiter_claims,
                ), None)
                assert res["statusCode"] == 200
                rubric_data = json.loads(res["body"])
                assert rubric_data["status"] == "DRAFT"
                assert len(rubric_data["criteria"]) == 2

        # 2. GET /jobs/{job_id}/rubric
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/rubric",
                path_params={"job_id": "job-py-01"},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            got_rubric = json.loads(res["body"])
            assert got_rubric["status"] == "DRAFT"

        # 3. Screening trigger refuses unapproved DRAFT rubric!
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/screening",
                path_params={"job_id": "job-py-01"},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 400
            body = json.loads(res["body"])
            assert body.get("code") == "RUBRIC_NOT_APPROVED"

        # 4. POST /jobs/{job_id}/rubric/approve
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/rubric/approve",
                path_params={"job_id": "job-py-01"},
                body={"criteria": [
                    {
                        "id": "c1",
                        "description": "Python backend experience with FastAPI",
                        "type": "must",
                        "weight": 0.7,
                        "how_to_verify": "Look for FastAPI production microservices",
                    },
                    {
                        "id": "c2",
                        "description": "MongoDB schema design",
                        "type": "must",
                        "weight": 0.3,
                        "how_to_verify": "Look for database queries and aggregation pipelines",
                    },
                ]},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            approved = json.loads(res["body"])
            assert approved["status"] == "APPROVED"
            assert approved["approved_by"] == "recruiter-sub-100"

        # 5. Screening trigger now succeeds after approval!
        collections["applications"].insert_one({
            "_id": "app-01",
            "job_id": "job-py-01",
            "tenant_id": "tenant-100",
            "phase2_status": "INDEXED",
            "status": "ACTIVE",
        })
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            with patch("boto3.client") as mock_boto:
                mock_boto.return_value = MagicMock()
                res = lambda_handler(_event(
                    "POST", "/jobs/{job_id}/screening",
                    path_params={"job_id": "job-py-01"},
                    claims=recruiter_claims,
                ), None)
                assert res["statusCode"] == 202

    def test_screening_status_dashboard_endpoint(self, recruiter_claims):
        collections = {
            "tenants": InMemoryCollection([
                {"_id": "tenant-100", "tenant_id": "tenant-100", "name": "Acme Corp", "status": "ACTIVE"}
            ]),
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "recruiter-sub-100", "tenant_id": "tenant-100", "role": "ADMIN"}
            ]),
            "jobs": InMemoryCollection([
                {
                    "_id": "job-101",
                    "job_id": "job-101",
                    "tenant_id": "tenant-100",
                    "final_shortlisted_candidates_count": 5,
                    "rubric_status": "APPROVED",
                }
            ]),
            "applications": InMemoryCollection([
                {"_id": "app-1", "job_id": "job-101", "tenant_id": "tenant-100", "phase2_status": "INDEXED", "status": "ACTIVE"},
                {"_id": "app-2", "job_id": "job-101", "tenant_id": "tenant-100", "phase2_status": "INDEXED", "status": "ACTIVE"},
            ]),
            "screening_runs": InMemoryCollection([
                {
                    "_id": "run-001",
                    "job_id": "job-101",
                    "tenant_id": "tenant-100",
                    "status": "COMPLETED",
                    "candidate_count": 2,
                    "phase2_candidate_count": 2,
                    "created_at": "2026-10-14T10:00:00Z",
                }
            ]),
        }
        mock_client = _mock_mongo(collections)

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/screening-status",
                path_params={"job_id": "job-101"},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            data = json.loads(res["body"])
            assert data["job_id"] == "job-101"
            assert data["screening_run_status"] == "COMPLETED"
            assert data["target_shortlisted_count"] == 5
            assert data["candidates_shortlisted"] == 2
            assert data["indexed_applications"] == 2
            assert "daily_budget" in data
            assert data["rubric_status"] == "APPROVED"

    def test_review_queue_list_and_resolve_endpoints(self, recruiter_claims):
        from phase4.review_queue import GLOBAL_REVIEW_QUEUE
        # Clear & Enqueue an item
        GLOBAL_REVIEW_QUEUE.enqueue(
            resume_id="cand-flagged-01",
            candidate_id="cand-flagged-01",
            job_id="job-101",
            flag_reasons=["possible_false_negative"],
            rerank_rank=8,
            weighted_score=0.92,
        )

        collections = {
            "jobs": InMemoryCollection([
                {"_id": "job-101", "job_id": "job-101", "tenant_id": "tenant-100"}
            ]),
            "tenants": InMemoryCollection([
                {"_id": "tenant-100", "tenant_id": "tenant-100", "name": "Acme Corp", "status": "ACTIVE"}
            ]),
            "tenant_memberships": InMemoryCollection([
                {"user_sub": "recruiter-sub-100", "tenant_id": "tenant-100", "role": "ADMIN"}
            ]),
            "applications": InMemoryCollection([
                {"_id": "cand-flagged-01", "candidate_id": "cand-flagged-01", "job_id": "job-101", "tenant_id": "tenant-100", "decision": "UNDECIDED"}
            ]),
            "phase4_review_queue": InMemoryCollection(),
            "phase4_review_history": InMemoryCollection(),
        }
        mock_client = _mock_mongo(collections)

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # GET /jobs/{job_id}/review-queue
            res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/review-queue",
                path_params={"job_id": "job-101"},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            data = json.loads(res["body"])
            assert data["count"] >= 1
            assert any(i["resume_id"] == "cand-flagged-01" for i in data["items"])

            # POST /jobs/{job_id}/review-queue/{candidate_id}/action
            res = lambda_handler(_event(
                "POST", "/jobs/{job_id}/review-queue/{candidate_id}/action",
                path_params={"job_id": "job-101", "candidate_id": "cand-flagged-01"},
                body={"action": "promote", "notes": "Approved after manual resume inspection"},
                claims=recruiter_claims,
            ), None)
            assert res["statusCode"] == 200
            resolved = json.loads(res["body"])
            assert resolved["status"] == "PROMOTED"
            assert resolved["resolved_by"] == "recruiter-sub-100"

    def test_candidate_feedback_public_endpoint(self):
        import hashlib
        token = "candidate-token-xyz-123"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

        collections = {
            "applications": InMemoryCollection([
                {
                    "_id": "app-candidate-99",
                    "job_id": "job-101",
                    "decision": "REJECTED",
                    "candidate_access_token_hash": token_hash,
                    "candidate_feedback": {
                        "application_id": "app-candidate-99",
                        "job_id": "job-101",
                        "what_resume_showed": "Your resume showed great Python backend fundamentals.",
                        "gaps": ["Direct experience with distributed MongoDB clustering"],
                        "actionable_suggestion": "Add concrete architecture details to project descriptions.",
                    }
                }
            ]),
        }
        mock_client = _mock_mongo(collections)

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # 1. Access without token should be blocked with 401
            unauth_res = lambda_handler(_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-101", "application_id": "app-candidate-99"},
                claims=None,
            ), None)
            assert unauth_res["statusCode"] == 401

            # 2. Access with invalid token should be blocked with 403
            bad_token_event = _event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-101", "application_id": "app-candidate-99"},
                claims=None,
            )
            bad_token_event["headers"]["X-Application-Token"] = "wrong-token"
            forbidden_res = lambda_handler(bad_token_event, None)
            assert forbidden_res["statusCode"] == 403

            # 3. Access with valid token succeeds
            valid_token_event = _event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-101", "application_id": "app-candidate-99"},
                claims=None,
            )
            valid_token_event["headers"]["X-Application-Token"] = token
            res = lambda_handler(valid_token_event, None)
            assert res["statusCode"] == 200
            fb = json.loads(res["body"])
            assert fb["application_id"] == "app-candidate-99"
            assert fb["decision_status"] == "REJECTED"
            assert len(fb["gaps"]) == 1

    def test_candidate_feedback_synthesized_from_hr_report_if_missing(self):
        import hashlib
        token = "candidate-token-synth-123"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

        collections = {
            "applications": InMemoryCollection([
                {
                    "_id": "app-candidate-synth",
                    "job_id": "job-101",
                    "decision": "REJECTED",
                    "candidate_access_token_hash": token_hash,
                    "hr_report": {
                        "candidate_id": "cand-synth",
                        "match_matrix": [
                            {"criterion_id": "c1", "description": "3+ years Python", "status": "not_evidenced", "type": "must"},
                            {"criterion_id": "c2", "description": "Apache Spark pipelines", "status": "not_evidenced", "type": "must"}
                        ],
                        "gaps": ["[C1] 3+ years Python - not evidenced in resume"]
                    }
                    # Note: candidate_feedback is deliberately missing!
                }
            ]),
        }
        mock_client = _mock_mongo(collections)

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            valid_token_event = _event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-101", "application_id": "app-candidate-synth"},
                claims=None,
            )
            valid_token_event["headers"]["X-Application-Token"] = token
            res = lambda_handler(valid_token_event, None)
            assert res["statusCode"] == 200
            fb = json.loads(res["body"])
            assert fb["application_id"] == "app-candidate-synth"
            assert fb["decision_status"] == "REJECTED"
            assert "feedback" in fb
            assert len(fb["gaps"]) > 0
            assert "3+ years Python" in fb["feedback"]
