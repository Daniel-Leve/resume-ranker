"""
Tests for Phase 4 Worker Integration and Backward Compatibility.
"""
from phase4.explainer import enrich_screening_candidates_with_explanations


def test_enrich_screening_candidates_preserves_existing_keys() -> None:
    jd = "Backend Engineer with Java and Spring Boot experience."
    raw_candidates = [
        {
            "candidate_id": "cand_01",
            "application_id": "app_01",
            "candidate_name": "Test Candidate",
            "rerank_rank": 1,
            "rerank_score": 0.954321,
            "rank_change": 2,
            "phase2": {
                "hybrid_score": 0.0823,
                "lexical_rank": 1,
                "vector_rank": 2,
                "matched_chunks": [{"chunk_id": "c1_chk", "section": "skills"}],
            },
            "source_key": "incoming/test.pdf",
        }
    ]

    enriched = enrich_screening_candidates_with_explanations(
        candidates=raw_candidates,
        job_description=jd,
        job_id="job_test",
        tenant_id="tenant_test",
    )

    assert len(enriched) == 1
    cand = enriched[0]

    # Check that all original keys are preserved exactly
    assert cand["candidate_id"] == "cand_01"
    assert cand["application_id"] == "app_01"
    assert cand["candidate_name"] == "Test Candidate"
    assert cand["rerank_rank"] == 1
    assert cand["rerank_score"] == 0.954321
    assert cand["rank_change"] == 2
    assert cand["source_key"] == "incoming/test.pdf"
    assert cand["phase2"]["hybrid_score"] == 0.0823

    # Check that explanation is attached
    assert "explanation" in cand
    explanation = cand["explanation"]
    assert explanation["candidate_id"] == "cand_01"
    assert explanation["rerank_rank"] == 1
    assert explanation["explanation_version"] == "1.0.0"


def test_enrich_screening_candidates_empty_list() -> None:
    enriched = enrich_screening_candidates_with_explanations(
        candidates=[],
        job_description="Some JD",
    )
    assert enriched == []
