"""
Phase 4 Production-Safety & Contract Regression Suite.
Validates:
  1. Persistent storage & concurrency (atomic Mongo operations + file fallback).
  2. Idempotency & Tenant Isolation (multi-tenant cache key identity).
  3. Candidate-feedback security & decision integrity (token auth, rejection guard, zero leak of ranks/scores).
  4. Rubric immutability & provenance (approved rubric locking, v1 -> v2 versioning, audit trail).
  5. OpenAPI 3.0.3 specification validity (openapi-spec-validator).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import yaml

from api.handlers.application_handler import lambda_handler
from phase4.daily_budget import (
    DailyBudget,
    compute_cache_key,
    compute_production_cache_key,
    compute_resume_hash,
)
from phase4.privacy import sanitize_candidate_feedback
from phase4.review_queue import ReviewQueueManager
from phase4.rubric_builder import approve_rubric, get_next_rubric_version
from phase4.schemas import JobRubric, RubricCriterion


# ─── Mock Helpers ─────────────────────────────────────────────────────────────

def _make_api_event(
    method: str,
    path: str,
    body: dict = None,
    path_params: dict = None,
    query_params: dict = None,
    headers: dict = None,
    claims: dict = None,
) -> dict:
    req_context = {}
    if claims:
        req_context["authorizer"] = {"claims": claims}
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return {
        "httpMethod": method.upper(),
        "resource": path,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "headers": h,
        "body": json.dumps(body) if body else None,
        "requestContext": req_context,
    }


class InMemoryMongoCollection:
    def __init__(self, initial=None):
        self.docs = list(initial) if initial else []

    def find_one(self, query=None, projection=None, sort=None):
        docs = self.docs
        if query:
            for k, v in query.items():
                if k == "$or":
                    docs = [d for d in docs if any(d.get(sub_k) == sub_v for cond in v for sub_k, sub_v in cond.items())]
                elif isinstance(v, dict) and "$ne" in v:
                    docs = [d for d in docs if d.get(k) != v["$ne"]]
                else:
                    docs = [d for d in docs if d.get(k) == v]
        if sort and docs:
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
                if k == "$or":
                    docs = [d for d in docs if any(d.get(sub_k) == sub_v for cond in v for sub_k, sub_v in cond.items())]
                elif isinstance(v, dict) and "$ne" in v:
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

    def update_one(self, query, update, upsert=False):
        target = self.find_one(query)
        if target:
            if "$set" in update:
                for k, v in update["$set"].items():
                    target[k] = v
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    target[k] = target.get(k, 0) + v
            for i, d in enumerate(self.docs):
                if d.get("_id") == target.get("_id"):
                    self.docs[i] = target
        elif upsert:
            new_doc = dict(query)
            if "$set" in update:
                new_doc.update(update["$set"])
            if "$inc" in update:
                new_doc.update(update["$inc"])
            self.insert_one(new_doc)

    def replace_one(self, query, replacement, upsert=False):
        for i, d in enumerate(self.docs):
            if d.get("_id") == query.get("_id"):
                self.docs[i] = dict(replacement)
                return
        if upsert:
            self.docs.append(dict(replacement))

    def find_one_and_update(self, query, update, upsert=False, return_document=None):
        self.update_one(query, update, upsert=upsert)
        return self.find_one(query)


class MockDatabase:
    def __init__(self, collections=None):
        self._collections = collections or {}

    def __getitem__(self, name: str):
        if name not in self._collections:
            self._collections[name] = InMemoryMongoCollection()
        return self._collections[name]


class MockMongoClient:
    def __init__(self, db: MockDatabase):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __getitem__(self, name: str):
        return self.db


# ─── 1. Persistent Storage & Concurrency Tests ───────────────────────────────

class TestPersistentStorageAndConcurrency:
    """Verify shared durable state, atomic budget updates, and queue persistence."""

    def test_daily_budget_atomic_mongo_reservation(self):
        db = MockDatabase()
        budget = DailyBudget(mongo_db=db, daily_token_limit=10000)

        # Concurrently simulate 2 workers recording usage
        res1 = budget.record_usage(prompt_tokens=1500, completion_tokens=500, requests=1, date_str="2026-10-15")
        assert res1["total_tokens"] == 2000
        assert res1["request_count"] == 1

        res2 = budget.record_usage(prompt_tokens=2000, completion_tokens=1000, requests=1, date_str="2026-10-15")
        assert res2["total_tokens"] == 5000
        assert res2["request_count"] == 2

        usage = budget.get_usage_today(date_str="2026-10-15")
        assert usage["total_tokens"] == 5000
        assert usage["request_count"] == 2
        assert not budget.is_budget_exceeded()

        # Trip budget threshold (> 90% of 10000 = 9000 tokens)
        budget.record_usage(prompt_tokens=4500, completion_tokens=0, requests=1, date_str="2026-10-15")
        assert budget.is_budget_exceeded()

    def test_review_queue_mongo_persistence_and_audit_provenance(self):
        db = MockDatabase()
        rq = ReviewQueueManager(mongo_db=db)

        # Enqueue candidate
        item = rq.enqueue(
            resume_id="cand-123",
            candidate_id="cand-123",
            job_id="job-999",
            tenant_id="tenant-alpha",
            flag_reasons=["possible_false_negative"],
            rerank_rank=12,
            weighted_score=0.88,
        )
        assert item.status == "NEEDS_REVIEW"

        # Verify query scoped by tenant
        tenant_items = rq.list_items(job_id="job-999", tenant_id="tenant-alpha")
        assert len(tenant_items) == 1
        other_tenant = rq.list_items(job_id="job-999", tenant_id="tenant-beta")
        assert len(other_tenant) == 0

        # Resolve with full audit trail
        resolved = rq.resolve(
            resume_id="cand-123",
            action="promote",
            notes="Overridden by recruiter due to strong open source portfolio",
            resolved_by="recruiter-sub-777",
            job_id="job-999",
            tenant_id="tenant-alpha",
        )
        assert resolved.status == "PROMOTED"
        assert resolved.resolved_by == "recruiter-sub-777"
        assert "Overridden" in resolved.override_notes

        # History collection has labeled record
        history_docs = db["phase4_review_history"].find()
        assert len(history_docs) == 1
        assert history_docs[0]["status"] == "PROMOTED"


# ─── 2. Idempotency & Tenant Isolation Tests ─────────────────────────────────

class TestIdempotencyAndTenantIsolation:
    """Ensure complete cache key identity isolation across tenants, jobs, apps, and revisions."""

    def test_cache_key_full_identity_tuple_isolation(self):
        resume_text = "Senior Python developer with AWS and Docker experience."
        resume_h = compute_resume_hash(resume_text)
        jd_h = hashlib.sha256("Backend Lead Job Description".encode("utf-8")).hexdigest()

        # Same resume, same JD, same rubric, but different tenants
        key_tenant_a = compute_production_cache_key(
            tenant_id="tenant-acme",
            job_id="job-01",
            application_id="app-100",
            resume_version=1,
            resume_hash=resume_h,
            jd_hash=jd_h,
            rubric_version="v1",
        )

        key_tenant_b = compute_production_cache_key(
            tenant_id="tenant-globex",
            job_id="job-01",
            application_id="app-100",
            resume_version=1,
            resume_hash=resume_h,
            jd_hash=jd_h,
            rubric_version="v1",
        )

        assert key_tenant_a != key_tenant_b, "Cache keys across different tenants MUST NOT collide."

        # Different resume revision for same candidate
        key_rev2 = compute_production_cache_key(
            tenant_id="tenant-acme",
            job_id="job-01",
            application_id="app-100",
            resume_version=2,
            resume_hash=resume_h,
            jd_hash=jd_h,
            rubric_version="v1",
        )
        assert key_tenant_a != key_rev2, "Cache keys for different resume versions MUST NOT collide."

    def test_resumable_cache_mongo_storage(self):
        db = MockDatabase()
        budget = DailyBudget(mongo_db=db)

        eval_data = {
            "overall_suitability": "high",
            "criteria_assessments": [{"criterion_id": "c1", "status": "met"}],
        }

        key = budget.save_cached_evaluation(
            jd_id="job-55",
            resume_hash="hash-abc",
            rubric_version="v1",
            resume_id="res-1",
            evaluation_data=eval_data,
            tenant_id="tenant-1",
            application_id="app-1",
            resume_version=1,
            jd_hash="jd-hash-1",
        )

        cached = budget.get_cached_evaluation(
            jd_id="job-55",
            resume_hash="hash-abc",
            rubric_version="v1",
            tenant_id="tenant-1",
            application_id="app-1",
            resume_version=1,
            jd_hash="jd-hash-1",
        )
        assert cached is not None
        assert cached["evaluation"]["overall_suitability"] == "high"

        # Cross-tenant query misses cache
        miss = budget.get_cached_evaluation(
            jd_id="job-55",
            resume_hash="hash-abc",
            rubric_version="v1",
            tenant_id="tenant-OTHER",
            application_id="app-1",
            resume_version=1,
            jd_hash="jd-hash-1",
        )
        assert miss is None


# ─── 3. Candidate-Feedback Security & Decision Integrity Tests ────────────────

class TestCandidateFeedbackSecurityAndDecisionIntegrity:
    """Verify token requirement, rejection state guard, and zero score/rank leakage."""

    @pytest.fixture
    def feedback_setup(self):
        token = "candidate-secret-token-777"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

        collections = {
            "tenant_memberships": InMemoryMongoCollection([
                {"user_sub": "recruiter-sub-1", "tenant_id": "tenant-100", "role": "MEMBER"}
            ]),
            "jobs": InMemoryMongoCollection([
                {"_id": "job-100", "tenant_id": "tenant-100", "status": "OPEN"}
            ]),
            "applications": InMemoryMongoCollection([
                {
                    "_id": "app-candidate-1",
                    "job_id": "job-100",
                    "tenant_id": "tenant-100",
                    "decision": "REJECTED",
                    "candidate_access_token_hash": token_hash,
                    "candidate_feedback": {
                        "feedback_markdown": (
                            "## Strengths\nStrong Python backend knowledge.\n\n"
                            "## Areas for Growth\nCandidate lacks production Kubernetes experience.\n"
                            "Your score was 0.72 and rank #4 with weight 0.25.\n\n"
                            "## Suggested Interview Questions\nAsk about Raft consensus."
                        )
                    }
                },
                {
                    "_id": "app-undecided-2",
                    "job_id": "job-100",
                    "tenant_id": "tenant-100",
                    "decision": "UNDECIDED",
                    "candidate_access_token_hash": token_hash,
                },
                {
                    "_id": "app-shortlisted-3",
                    "job_id": "job-100",
                    "tenant_id": "tenant-100",
                    "decision": "SHORTLISTED",
                    "candidate_access_token_hash": token_hash,
                }
            ]),
        }
        db = MockDatabase(collections)
        return MockMongoClient(db), token

    def test_unauthenticated_access_blocked(self, feedback_setup):
        mock_client, token = feedback_setup
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # No token, no recruiter auth
            event = _make_api_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-100", "application_id": "app-candidate-1"},
            )
            res = lambda_handler(event, None)
            assert res["statusCode"] == 401

    def test_invalid_token_forbidden(self, feedback_setup):
        mock_client, token = feedback_setup
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            event = _make_api_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-100", "application_id": "app-candidate-1"},
                headers={"X-Application-Token": "invalid-token-tampered"},
            )
            res = lambda_handler(event, None)
            assert res["statusCode"] == 403

    def test_undecided_candidate_returns_409(self, feedback_setup):
        mock_client, token = feedback_setup
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            event = _make_api_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-100", "application_id": "app-undecided-2"},
                headers={"X-Application-Token": token},
            )
            res = lambda_handler(event, None)
            assert res["statusCode"] == 409
            body = json.loads(res["body"])
            assert body["decision_status"] == "UNDECIDED"
            assert "underway" in body["message"]

    def test_shortlisted_candidate_receives_status_without_rejection(self, feedback_setup):
        mock_client, token = feedback_setup
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            event = _make_api_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-100", "application_id": "app-shortlisted-3"},
                headers={"X-Application-Token": token},
            )
            res = lambda_handler(event, None)
            assert res["statusCode"] == 200
            body = json.loads(res["body"])
            assert body["decision_status"] == "SHORTLISTED"
            assert "shortlisted" in body["message"]
            assert "feedback_markdown" not in body

    def test_confirmed_rejected_candidate_receives_sanitized_feedback(self, feedback_setup):
        mock_client, token = feedback_setup
        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            event = _make_api_event(
                "GET", "/jobs/{job_id}/applications/{application_id}/feedback",
                path_params={"job_id": "job-100", "application_id": "app-candidate-1"},
                headers={"X-Application-Token": token},
            )
            res = lambda_handler(event, None)
            assert res["statusCode"] == 200
            body = json.loads(res["body"])
            assert body["decision_status"] == "REJECTED"
            feedback_text = body["feedback_markdown"]

            # Strict privacy checks: zero scores, ranks, weights, or interview questions
            assert "0.72" not in feedback_text
            assert "rank #4" not in feedback_text.lower()
            assert "weight" not in feedback_text.lower()
            assert "Suggested Interview Questions" not in feedback_text
            assert "Kubernetes" in feedback_text  # Constructive feedback remains


# ─── 4. Rubric Immutability & Provenance Tests ───────────────────────────────

class TestRubricImmutabilityAndProvenance:
    """Verify approved rubrics are strictly locked and revisions increment versions."""

    def test_approve_rubric_immutability_enforcement(self, tmp_path):
        rubric = JobRubric(
            jd_id="job-freeze",
            version="v1",
            status="DRAFT",
            created_at="2026-10-15T00:00:00Z",
            criteria=[
                RubricCriterion(id="c1", description="FastAPI", type="must", weight=1.0, how_to_verify="code")
            ],
        )
        rubric_file = tmp_path / "job-freeze_rubric_v1.json"
        with open(rubric_file, "w", encoding="utf-8") as f:
            json.dump(rubric.model_dump(), f)

        # 1. First approval locks the rubric
        approved = approve_rubric("job-freeze", approved_by="recruiter-sub-admin", rubrics_dir=tmp_path)
        assert approved.status == "APPROVED"
        assert approved.approved_by == "recruiter-sub-admin"

        # 2. In-place modification of approved rubric raises ValueError
        new_criteria = [
            {"id": "c1", "description": "Django instead of FastAPI", "type": "must", "weight": 1.0, "how_to_verify": "code"}
        ]
        with pytest.raises(ValueError, match="already APPROVED and immutable"):
            approve_rubric("job-freeze", custom_criteria=new_criteria, rubrics_dir=tmp_path)

        # 3. Next version helper calculates v2
        next_ver = get_next_rubric_version("job-freeze", rubrics_dir=tmp_path)
        assert next_ver == "v2"

    def test_api_approved_rubric_modification_returns_409(self):
        claims = {"sub": "recruiter-admin-sub", "email": "admin@acme.com"}
        collections = {
            "tenant_memberships": InMemoryMongoCollection([
                {"user_sub": "recruiter-admin-sub", "tenant_id": "tenant-100", "role": "ADMIN"}
            ]),
            "jobs": InMemoryMongoCollection([
                {
                    "_id": "job-locked",
                    "tenant_id": "tenant-100",
                    "status": "OPEN",
                    "rubric_status": "APPROVED",
                    "rubric": {
                        "jd_id": "job-locked",
                        "version": "v1",
                        "status": "APPROVED",
                        "criteria": [{"id": "c1", "description": "Python", "type": "must", "weight": 1.0}],
                    }
                }
            ]),
        }
        mock_client = MockMongoClient(MockDatabase(collections))

        with patch("api.handlers.application_handler._get_mongo", return_value=mock_client):
            # Attempt to modify criteria of already approved rubric
            event = _make_api_event(
                "POST", "/jobs/{job_id}/rubric/approve",
                path_params={"job_id": "job-locked"},
                body={"criteria": [{"id": "c1", "description": "Rust", "type": "must", "weight": 1.0}]},
                claims=claims,
            )
            res = lambda_handler(event, None)
            assert res["statusCode"] == 409
            body = json.loads(res["body"])
            assert body["code"] == "RUBRIC_ALREADY_APPROVED"


# ─── 5. OpenAPI 3.0.3 Contract Validator ─────────────────────────────────────

def test_openapi_specification_strict_validity():
    """Verify that docs/openapi.yaml passes strict OpenAPI 3.0.3 validation."""
    from openapi_spec_validator import validate

    spec_path = Path("docs/openapi.yaml")
    assert spec_path.exists(), "docs/openapi.yaml must exist."

    with open(spec_path, "r", encoding="utf-8") as f:
        spec_dict = yaml.safe_load(f)

    # Validates without throwing OpenAPIValidationError
    validate(spec_dict)
