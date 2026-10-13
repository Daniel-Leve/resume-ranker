"""
Tests for Phase 4 Explainer Orchestrator and Ranking Preservation.
"""
from phase4.explainer import generate_explanations


def test_explainer_realistic_multi_candidate_fixture() -> None:
    jd_text = """
    Backend Engineer — Python / Cloud

    Required skills:
    - 3+ years of Python backend development
    - Experience with PostgreSQL database design
    - Docker containerization

    Nice to have:
    - AWS cloud experience (ECS, S3, SQS)
    - Redis caching
    """

    phase3_output = {
        "job_id": "backend-002",
        "retrieval_method": "hybrid",
        "rerank_model": "rerank-2.5",
        "candidates": [
            {
                "candidate_id": "cand_alice",
                "application_id": "app_alice",
                "candidate_name": "Alice Smith",
                "rerank_rank": 1,
                "rerank_score": 0.925,
                "rank_change": 0,
                "phase2": {
                    "hybrid_score": 0.12,
                    "matched_chunks": [
                        {"chunk_id": "alice_exp_0", "section": "experience"},
                        {"chunk_id": "alice_skills_0", "section": "skills"},
                    ],
                },
                "source_key": "incoming/alice.pdf",
            },
            {
                "candidate_id": "cand_bob",
                "application_id": "app_bob",
                "candidate_name": "Bob Jones",
                "rerank_rank": 2,
                "rerank_score": 0.810,
                "rank_change": 1,
                "phase2": {
                    "hybrid_score": 0.09,
                    "matched_chunks": [
                        {"chunk_id": "bob_exp_0", "section": "experience"},
                    ],
                },
                "source_key": "incoming/bob.pdf",
            },
            {
                "candidate_id": "cand_carol",
                "application_id": "app_carol",
                "candidate_name": "Carol White",
                "rerank_rank": 3,
                "rerank_score": 0.650,
                "rank_change": -1,
                "phase2": {
                    "hybrid_score": 0.05,
                    "matched_chunks": [
                        {"chunk_id": "carol_edu_0", "section": "education"},
                    ],
                },
                "source_key": "incoming/carol.pdf",
            },
        ],
    }

    chunks_map = {
        "cand_alice": [
            {
                "chunk_id": "alice_exp_0",
                "section": "experience",
                "text": "Senior Python developer building high-throughput APIs with PostgreSQL and Redis caching.",
            },
            {
                "chunk_id": "alice_skills_0",
                "section": "skills",
                "text": "Docker, Kubernetes, AWS (S3, ECS, SQS), Git, CI/CD",
            },
        ],
        "cand_bob": [
            {
                "chunk_id": "bob_exp_0",
                "section": "experience",
                "text": "Python software engineer with 4 years experience creating Docker microservices.",
            }
        ],
        "cand_carol": [
            {
                "chunk_id": "carol_edu_0",
                "section": "education",
                "text": "B.S. in Computer Science. Coursework in database systems and software engineering.",
            }
        ],
    }

    report = generate_explanations(
        phase3_output=phase3_output,
        job_description=jd_text,
        candidate_chunks_map=chunks_map,
        job_id="backend-002",
        tenant_id="tenant-alpha",
        screening_run_id="run-999",
    )

    # 1. Output counts and metadata
    assert report.job_id == "backend-002"
    assert report.tenant_id == "tenant-alpha"
    assert report.screening_run_id == "run-999"
    assert report.candidate_count == 3
    assert len(report.candidates) == 3

    # 2. Faithful preservation of candidate order and final ranks
    ranks = [c.rerank_rank for c in report.candidates]
    assert ranks == [1, 2, 3]
    candidate_ids = [c.candidate_id for c in report.candidates]
    assert candidate_ids == ["cand_alice", "cand_bob", "cand_carol"]

    # 3. Candidate 1 (Alice) verification
    alice = report.candidates[0]
    assert alice.candidate_id == "cand_alice"
    assert alice.application_id == "app_alice"
    assert alice.candidate_name == "Alice Smith"
    assert alice.rerank_score == 0.925
    assert "experience" in alice.matched_sections
    assert "skills" in alice.matched_sections
    assert len(alice.supporting_evidence) >= 2
    # Verify Python, PostgreSQL, Docker matched
    alice_supported = [r.requirement for r in alice.requirement_alignment if r.status == "supported"]
    assert any("Python" in req for req in alice_supported)
    assert any("PostgreSQL" in req for req in alice_supported)

    # 4. Candidate 2 (Bob) verification
    bob = report.candidates[1]
    assert bob.rerank_rank == 2
    assert "experience" in bob.matched_sections
    bob_supported = [r.requirement for r in bob.requirement_alignment if r.status == "supported"]
    assert any("Python" in req for req in bob_supported)

    # 5. Candidate 3 (Carol) - weak/no match in education chunk
    carol = report.candidates[2]
    assert carol.rerank_rank == 3
    assert "education" in carol.matched_sections
    assert len(carol.evidence_gaps) > 0


def test_explainer_preserves_order_and_rank_strictly() -> None:
    jd = "Software Engineer with Java skills"
    phase3 = {
        "job_id": "test-job",
        "candidates": [
            {"candidate_id": "c3", "rerank_rank": 1, "rerank_score": 0.9},
            {"candidate_id": "c1", "rerank_rank": 2, "rerank_score": 0.8},
            {"candidate_id": "c2", "rerank_rank": 3, "rerank_score": 0.7},
        ],
    }

    report = generate_explanations(
        phase3_output=phase3,
        job_description=jd,
        candidate_chunks_map={},
    )

    assert [c.candidate_id for c in report.candidates] == ["c3", "c1", "c2"]
    assert [c.rerank_rank for c in report.candidates] == [1, 2, 3]


def test_explainer_idempotency() -> None:
    jd = "Backend Developer with Go and SQL"
    phase3 = {
        "job_id": "job-idem",
        "candidates": [
            {"candidate_id": "cand_x", "rerank_rank": 1, "rerank_score": 0.85},
        ],
    }
    chunks = {
        "cand_x": [{"chunk_id": "chk_1", "section": "skills", "text": "Go, SQL, Kubernetes"}]
    }

    rep1 = generate_explanations(phase3, jd, candidate_chunks_map=chunks).to_dict()
    rep2 = generate_explanations(phase3, jd, candidate_chunks_map=chunks).to_dict()

    assert rep1 == rep2


def test_custom_provider_modular_interface() -> None:
    from phase4.provider import BaseExplanationProvider
    from phase4.models import CandidateExplanation

    class MockLLMProvider(BaseExplanationProvider):
        def generate_candidate_explanation(self, candidate_data, candidate_chunks, requirements):
            return CandidateExplanation(
                candidate_id=candidate_data["candidate_id"],
                rerank_rank=candidate_data.get("rerank_rank", 1),
                summary="Mock LLM explanation generated under strict evidence constraints.",
                matched_sections=["experience"],
            )

    phase3 = {
        "job_id": "custom-provider-job",
        "candidates": [{"candidate_id": "cand_llm", "rerank_rank": 1, "rerank_score": 0.99}],
    }

    report = generate_explanations(
        phase3_output=phase3,
        job_description="Software Engineer",
        provider=MockLLMProvider(),
        candidate_chunks_map={"cand_llm": []},
    )

    assert report.generator_type == "custom"
    assert report.candidates[0].summary == "Mock LLM explanation generated under strict evidence constraints."
    assert report.candidates[0].rerank_rank == 1


def test_explainer_malformed_inputs() -> None:
    # Handles candidates with missing optional keys without crashing
    phase3_malformed = {
        "job_id": "malformed-job",
        "candidates": [
            {"candidate_id": "cand_sparse"},
            {"candidate_id": "cand_sparse_2", "phase2": None},
        ],
    }

    report = generate_explanations(
        phase3_output=phase3_malformed,
        job_description="Requirements here",
        candidate_chunks_map={},
    )

    assert len(report.candidates) == 2
    assert report.candidates[0].candidate_id == "cand_sparse"
    assert report.candidates[0].rerank_rank == 1
    assert report.candidates[1].candidate_id == "cand_sparse_2"
    assert report.candidates[1].rerank_rank == 2
