"""
Tests for Phase 4 Explanation Provider.
"""
from phase4.models import JobRequirement
from phase4.provider import DeterministicExplanationProvider


def test_deterministic_provider_supported_requirement() -> None:
    provider = DeterministicExplanationProvider()
    candidate_data = {
        "candidate_id": "cand_01",
        "rerank_rank": 1,
        "rerank_score": 0.892,
        "phase2": {
            "matched_chunks": [{"chunk_id": "c1_exp_0", "section": "experience"}],
        },
    }
    chunks = [
        {
            "chunk_id": "c1_exp_0",
            "section": "experience",
            "text": "Built enterprise microservices using Java and Spring Boot deployed on AWS ECS.",
        }
    ]
    reqs = [
        JobRequirement(text="Java development with Spring Boot", category="required", keywords=["Java", "Spring Boot"]),
        JobRequirement(text="Familiarity with Kubernetes", category="required", keywords=["Kubernetes"]),
    ]

    explanation = provider.generate_candidate_explanation(candidate_data, chunks, reqs)

    assert explanation.candidate_id == "cand_01"
    assert explanation.rerank_rank == 1
    assert explanation.rerank_score == 0.892
    assert "Experience" in explanation.summary or "experience" in explanation.summary

    # Requirement 1 should be supported
    assert explanation.requirement_alignment[0].status == "supported"
    assert "c1_exp_0" in explanation.requirement_alignment[0].supporting_chunks
    assert len(explanation.requirement_alignment[0].evidence_excerpts) > 0

    # Requirement 2 should not be established
    assert explanation.requirement_alignment[1].status == "not_established"
    assert len(explanation.evidence_gaps) == 1
    assert "Kubernetes" in explanation.evidence_gaps[0]

    # Verify supporting evidence list
    assert len(explanation.supporting_evidence) >= 1
    assert explanation.supporting_evidence[0].chunk_id == "c1_exp_0"
    assert explanation.supporting_evidence[0].section == "experience"
    assert explanation.supporting_evidence[0].content_hash is not None


def test_deterministic_provider_empty_chunks() -> None:
    provider = DeterministicExplanationProvider()
    candidate_data = {
        "candidate_id": "cand_empty",
        "rerank_rank": 4,
        "rerank_score": 0.45,
    }
    reqs = [
        JobRequirement(text="Proficiency in Python", category="required", keywords=["Python"])
    ]

    explanation = provider.generate_candidate_explanation(candidate_data, [], reqs)

    assert explanation.rerank_rank == 4
    assert "No retrieved resume chunks" in explanation.summary
    assert len(explanation.supporting_evidence) == 0
    assert explanation.requirement_alignment[0].status == "not_established"
    assert any("No chunk texts were available" in lim for lim in explanation.limitations)


def test_deterministic_provider_audit_limitations_and_bias_free() -> None:
    provider = DeterministicExplanationProvider()
    candidate_data = {"candidate_id": "cand_02", "rerank_rank": 2}
    chunks = [{"chunk_id": "c_skills_0", "section": "skills", "text": "Python, Docker, SQL"}]
    reqs = [JobRequirement(text="Docker containerization", category="required", keywords=["Docker"])]

    explanation = provider.generate_candidate_explanation(candidate_data, chunks, reqs)

    # Verify standard audit limitations are present
    assert any("Explanations reflect only the resume chunks retrieved" in lim for lim in explanation.limitations)
    assert any("No protected personal characteristics" in lim for lim in explanation.limitations)
    # Ensure no demographic inferences exist
    full_text = str(explanation.to_dict()).lower()
    for forbidden in ["gender", "race", "ethnicity", "religion", "age"]:
        assert forbidden not in explanation.summary.lower()


def test_models_serialization_roundtrip() -> None:
    from phase4.models import (
        SupportingEvidence,
        RequirementAlignment,
        CandidateExplanation,
        Phase4Report,
    )

    ev = SupportingEvidence(
        chunk_id="chunk_1",
        section="skills",
        excerpt="Python and AWS",
        relevance_keyword="Python",
    )
    ev_dict = ev.to_dict()
    assert SupportingEvidence.from_dict(ev_dict).to_dict() == ev_dict

    req = RequirementAlignment(
        requirement="Python skills",
        category="required",
        status="supported",
        supporting_chunks=["chunk_1"],
        evidence_excerpts=["Python and AWS"],
        rationale="Matches requirement",
    )
    req_dict = req.to_dict()
    assert RequirementAlignment.from_dict(req_dict).to_dict() == req_dict

    cand = CandidateExplanation(
        candidate_id="cand_1",
        rerank_rank=1,
        summary="Ranked #1",
        matched_sections=["skills"],
        supporting_evidence=[ev],
        requirement_alignment=[req],
    )
    cand_dict = cand.to_dict()
    assert CandidateExplanation.from_dict(cand_dict).to_dict() == cand_dict

    report = Phase4Report(
        job_id="job_1",
        candidate_count=1,
        candidates=[cand],
        tenant_id="tenant_1",
    )
    rep_dict = report.to_dict()
    assert Phase4Report.from_dict(rep_dict).to_dict() == rep_dict
