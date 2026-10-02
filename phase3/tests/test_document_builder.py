"""
Unit tests for phase3.reranker.document_builder
"""
from __future__ import annotations

from unittest.mock import MagicMock

from phase3.reranker.document_builder import build_candidate_document


def test_build_candidate_document_success():
    """Test standard document reconstruction."""
    mock_collection = MagicMock()
    
    # Mock chunks
    mock_cursor = [
        {"chunk_id": "cand_summary_00", "section": "summary", "text": "Experienced engineer.", "chunk_index": 0},
        {"chunk_id": "cand_experience_00", "section": "experience", "text": "Worked at TechCorp.", "chunk_index": 1}
    ]
    
    mock_find = MagicMock()
    mock_find.sort.return_value = mock_cursor
    mock_collection.find.return_value = mock_find
    
    doc = build_candidate_document(mock_collection, "cand123", max_chars=1000)
    
    assert doc.candidate_id == "cand123"
    assert doc.truncated is False
    assert len(doc.chunk_ids) == 2
    assert "[CANDIDATE PROFILE]" in doc.text
    assert "[SUMMARY]" in doc.text
    assert "Experienced engineer." in doc.text
    assert "[EXPERIENCE]" in doc.text
    assert "Worked at TechCorp." in doc.text
    
    # Verify find was called with right arguments
    mock_collection.find.assert_called_once_with(
        {"candidate_id": "cand123"},
        {"chunk_id": 1, "section": 1, "text": 1, "chunk_index": 1, "_id": 0}
    )


def test_build_candidate_document_truncation():
    """Test document truncation when max_chars is exceeded."""
    mock_collection = MagicMock()
    
    mock_cursor = [
        {"chunk_id": "cand_summary_00", "section": "summary", "text": "A" * 100, "chunk_index": 0},
        {"chunk_id": "cand_experience_00", "section": "experience", "text": "B" * 100, "chunk_index": 1}
    ]
    
    mock_find = MagicMock()
    mock_find.sort.return_value = mock_cursor
    mock_collection.find.return_value = mock_find
    
    # Limit chars severely, but enough to let the first chunk pass
    doc = build_candidate_document(mock_collection, "cand123", max_chars=180)
    
    assert doc.truncated is True
    # Should include summary, but experience will be truncated
    assert "A" * 100 in doc.text
    assert "B" * 100 not in doc.text
    assert "[TRUNCATED]" in doc.text


def test_build_candidate_document_empty():
    """Test candidate not found in Mongo."""
    mock_collection = MagicMock()
    
    mock_find = MagicMock()
    mock_find.sort.return_value = []
    mock_collection.find.return_value = mock_find
    
    doc = build_candidate_document(mock_collection, "cand123", max_chars=1000)
    
    assert doc.text == ""
    assert doc.chunk_ids == []
    assert doc.truncated is False
