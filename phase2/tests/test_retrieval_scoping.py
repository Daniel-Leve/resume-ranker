"""
Unit tests for Phase 2 retrieval query construction and multi-tenant scoping.
"""
from __future__ import annotations

import pytest

from phase2.retrieval.lexical_search import build_lexical_search_pipeline
from phase2.retrieval.vector_search import build_vector_search_pipeline


class TestVectorSearchScoping:
    def test_unscoped_legacy_pipeline(self):
        dummy_embedding = [0.1] * 1024
        pipeline = build_vector_search_pipeline(
            query_embedding=dummy_embedding,
            k=15,
            num_candidates=150,
            tenant_id=None,
            job_id=None,
        )

        stage = pipeline[0]["$vectorSearch"]
        assert "filter" not in stage
        assert stage["limit"] == 15
        assert stage["numCandidates"] == 150
        assert stage["path"] == "embedding"

    def test_scoped_saas_pipeline_both_tenant_and_job(self):
        dummy_embedding = [0.1] * 1024
        pipeline = build_vector_search_pipeline(
            query_embedding=dummy_embedding,
            k=10,
            num_candidates=100,
            tenant_id="tenant_acme_corp",
            job_id="job_backend_001",
        )

        stage = pipeline[0]["$vectorSearch"]
        assert "filter" in stage
        assert stage["filter"] == {
            "tenant_id": {"$eq": "tenant_acme_corp"},
            "job_id": {"$eq": "job_backend_001"},
        }

    def test_scoped_tenant_only(self):
        dummy_embedding = [0.1] * 1024
        pipeline = build_vector_search_pipeline(
            query_embedding=dummy_embedding,
            k=10,
            num_candidates=100,
            tenant_id="tenant_acme_corp",
            job_id=None,
        )

        stage = pipeline[0]["$vectorSearch"]
        assert stage["filter"] == {
            "tenant_id": {"$eq": "tenant_acme_corp"}
        }

    def test_whitespace_stripped_and_empty_ignored(self):
        dummy_embedding = [0.1] * 1024
        pipeline = build_vector_search_pipeline(
            query_embedding=dummy_embedding,
            k=10,
            num_candidates=100,
            tenant_id="  tenant_acme  ",
            job_id="   ",
        )

        stage = pipeline[0]["$vectorSearch"]
        assert stage["filter"] == {
            "tenant_id": {"$eq": "tenant_acme"}
        }


class TestLexicalSearchScoping:
    def test_unscoped_legacy_pipeline(self):
        pipeline = build_lexical_search_pipeline(
            query_text="Python AWS developer",
            k=15,
            tenant_id=None,
            job_id=None,
        )

        stage = pipeline[0]["$search"]
        assert "compound" not in stage
        assert stage["text"]["query"] == "Python AWS developer"
        assert stage["text"]["path"] == "text"

    def test_scoped_saas_pipeline_both_tenant_and_job(self):
        pipeline = build_lexical_search_pipeline(
            query_text="Python AWS developer",
            k=15,
            tenant_id="tenant_acme_corp",
            job_id="job_backend_001",
        )

        stage = pipeline[0]["$search"]
        assert "compound" in stage
        compound = stage["compound"]
        assert compound["must"] == [{"text": {"query": "Python AWS developer", "path": "text"}}]
        assert compound["filter"] == [
            {"equals": {"path": "tenant_id", "value": "tenant_acme_corp"}},
            {"equals": {"path": "job_id", "value": "job_backend_001"}},
        ]

    def test_scoped_tenant_only(self):
        pipeline = build_lexical_search_pipeline(
            query_text="Python AWS developer",
            k=15,
            tenant_id="tenant_acme_corp",
            job_id=None,
        )

        stage = pipeline[0]["$search"]
        compound = stage["compound"]
        assert compound["filter"] == [
            {"equals": {"path": "tenant_id", "value": "tenant_acme_corp"}}
        ]

    def test_whitespace_stripped_and_empty_ignored(self):
        pipeline = build_lexical_search_pipeline(
            query_text="Python AWS developer",
            k=15,
            tenant_id="  tenant_acme  ",
            job_id="   ",
        )

        stage = pipeline[0]["$search"]
        compound = stage["compound"]
        assert compound["filter"] == [
            {"equals": {"path": "tenant_id", "value": "tenant_acme"}}
        ]
