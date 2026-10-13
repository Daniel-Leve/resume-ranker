"""
Tests for Multi-Tenant, Job, Application, and Resume-Version Evidence Isolation.
"""
from unittest.mock import MagicMock
from phase4.explainer import fetch_candidate_chunks_from_db


def test_fetch_candidate_chunks_scoping() -> None:
    mock_collection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = [
        {"chunk_id": "c1", "section": "experience", "text": "Python engineer"}
    ]
    mock_collection.find.return_value = mock_cursor

    # Call with full SaaS context
    result = fetch_candidate_chunks_from_db(
        collection=mock_collection,
        candidate_id="cand_123",
        tenant_id="tenant_abc",
        job_id="job_456",
        application_id="app_789",
        resume_version=2,
    )

    assert len(result) == 1
    # Verify find() call arguments strictly scoped
    call_args, _ = mock_collection.find.call_args
    query = call_args[0]

    assert query["candidate_id"] == "cand_123"
    assert query["tenant_id"] == "tenant_abc"
    assert query["job_id"] == "job_456"
    assert query["application_id"] == "app_789"
    assert query["resume_version"] == 2


def test_fetch_candidate_chunks_prevents_cross_tenant_leakage() -> None:
    mock_collection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = []
    mock_collection.find.return_value = mock_cursor

    fetch_candidate_chunks_from_db(
        collection=mock_collection,
        candidate_id="cand_999",
        tenant_id="tenant_isolated",
        job_id="job_isolated",
    )

    query = mock_collection.find.call_args[0][0]
    assert query["tenant_id"] == "tenant_isolated"
    assert query["job_id"] == "job_isolated"
    assert "tenant_other" not in query
