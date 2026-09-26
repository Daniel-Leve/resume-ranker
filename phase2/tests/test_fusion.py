"""
Unit tests for phase2.retrieval.fusion

Tests cover:
- RRF score mathematics
- Candidates in both result lists
- Candidates in lexical-only or vector-only list
- Multi-chunk deduplication per candidate
- top-k truncation
- Null rank handling (never invented)
- Score ordering (both > single method)
- Empty input lists
- Provenance preservation (matched_chunks, source_key)
"""
from __future__ import annotations

import pytest

from phase2.retrieval.fusion import CandidateProvenance, fuse_results, rrf_score
from phase2.retrieval.lexical_search import ChunkHit


# ─── RRF score math ────────────────────────────────────────────────────────────

class TestRrfScore:

    def test_rank_1_k60(self):
        assert rrf_score(1, 60) == pytest.approx(1 / 61)

    def test_rank_60_k60(self):
        assert rrf_score(60, 60) == pytest.approx(1 / 120)

    def test_score_decreases_with_rank(self):
        assert rrf_score(1) > rrf_score(5) > rrf_score(10) > rrf_score(100)

    def test_custom_k(self):
        assert rrf_score(1, k=0) == pytest.approx(1.0)   # degenerate: k=0
        assert rrf_score(1, k=1) == pytest.approx(0.5)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hit(candidate_id: str, chunk_suffix: str, section: str = "experience",
         source_key: str = "extracted/job123.json") -> ChunkHit:
    return ChunkHit(
        candidate_id=candidate_id,
        chunk_id=f"{candidate_id}_{chunk_suffix}",
        section=section,
        source_key=source_key,
    )


# ─── Basic fusion ─────────────────────────────────────────────────────────────

class TestFuseResults:

    def test_both_methods_returns_all_candidates(self):
        lex = [_hit("cand-a", "exp_00"), _hit("cand-b", "skills_00")]
        vec = [_hit("cand-b", "exp_00"), _hit("cand-c", "skills_00")]
        results = fuse_results(lex, vec, final_top_k=10)
        ids = {r.candidate_id for r in results}
        assert "cand-a" in ids
        assert "cand-b" in ids
        assert "cand-c" in ids

    def test_lexical_only(self):
        lex = [_hit("cand-a", "exp_00")]
        results = fuse_results(lex, [], final_top_k=10)
        assert len(results) == 1
        prov = results[0]
        assert prov.candidate_id == "cand-a"
        assert prov.lexical_rank == 1
        assert prov.vector_rank is None

    def test_vector_only(self):
        vec = [_hit("cand-a", "exp_00")]
        results = fuse_results([], vec, final_top_k=10)
        assert len(results) == 1
        prov = results[0]
        assert prov.vector_rank == 1
        assert prov.lexical_rank is None

    def test_empty_inputs(self):
        results = fuse_results([], [], final_top_k=10)
        assert results == []


# ─── Deduplication ────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_multi_chunk_same_candidate_deduped(self):
        """Multiple chunks for one candidate → single result."""
        lex = [
            _hit("cand-a", "exp_00"),
            _hit("cand-a", "exp_01"),
            _hit("cand-a", "skills_00"),
        ]
        results = fuse_results(lex, [], final_top_k=10)
        a_results = [r for r in results if r.candidate_id == "cand-a"]
        assert len(a_results) == 1

    def test_multi_chunk_matched_chunks_collected(self):
        """All matching chunks are preserved in matched_chunks."""
        lex = [
            _hit("cand-a", "exp_00"),
            _hit("cand-a", "exp_01"),
            _hit("cand-a", "skills_00"),
        ]
        results = fuse_results(lex, [], final_top_k=10)
        prov = results[0]
        assert len(prov.matched_chunks) == 3

    def test_unique_candidate_ids_in_output(self):
        """Output must have no duplicate candidate_ids."""
        lex = [
            _hit("cand-a", "exp_00"),
            _hit("cand-b", "exp_00"),
            _hit("cand-a", "skills_00"),
        ]
        vec = [_hit("cand-a", "edu_00"), _hit("cand-c", "exp_00")]
        results = fuse_results(lex, vec, final_top_k=10)
        ids = [r.candidate_id for r in results]
        assert len(ids) == len(set(ids)), "Duplicate candidate_ids in output"


# ─── Top-k truncation ─────────────────────────────────────────────────────────

class TestTopK:

    def test_truncated_to_top_k(self):
        lex = [_hit(f"cand-{i}", "exp_00") for i in range(20)]
        results = fuse_results(lex, [], final_top_k=5)
        assert len(results) == 5

    def test_fewer_than_top_k_returns_all(self):
        lex = [_hit("cand-a", "exp_00"), _hit("cand-b", "exp_00")]
        results = fuse_results(lex, [], final_top_k=100)
        assert len(results) == 2


# ─── Rank provenance ──────────────────────────────────────────────────────────

class TestRankProvenance:

    def test_null_rank_not_invented_lexical(self):
        """Candidate only in vector results → lexical_rank must be None."""
        vec = [_hit("cand-a", "exp_00")]
        results = fuse_results([], vec, final_top_k=10)
        prov = results[0]
        assert prov.lexical_rank is None

    def test_null_rank_not_invented_vector(self):
        """Candidate only in lexical results → vector_rank must be None."""
        lex = [_hit("cand-a", "exp_00")]
        results = fuse_results(lex, [], final_top_k=10)
        prov = results[0]
        assert prov.vector_rank is None

    def test_best_rank_stored_multi_chunk(self):
        """Best (minimum) rank across all chunks is stored, not the last rank."""
        lex = [
            _hit("cand-x", "exp_00"),   # rank 1 — best
            _hit("cand-y", "exp_00"),   # rank 2
            _hit("cand-x", "skills_00"),# rank 3
        ]
        results = fuse_results(lex, [], final_top_k=10)
        cand_x = next(r for r in results if r.candidate_id == "cand-x")
        assert cand_x.lexical_rank == 1  # best rank, not 3

    def test_both_methods_both_ranks_set(self):
        lex = [_hit("cand-a", "exp_00"), _hit("cand-b", "skills_00")]
        vec = [_hit("cand-b", "exp_00"), _hit("cand-a", "skills_00")]
        results = fuse_results(lex, vec, final_top_k=10)
        for prov in results:
            assert prov.lexical_rank is not None
            assert prov.vector_rank is not None

    def test_source_key_preserved(self):
        lex = [_hit("cand-a", "exp_00", source_key="extracted/my_job_id.json")]
        results = fuse_results(lex, [], final_top_k=10)
        assert results[0].source_key == "extracted/my_job_id.json"


# ─── Score ordering ───────────────────────────────────────────────────────────

class TestScoreOrdering:

    def test_both_methods_higher_than_single(self):
        """A candidate in both methods should score higher than one in only one."""
        lex = [
            _hit("cand-both", "exp_00"),   # rank 1 lex
            _hit("cand-lex-only", "exp_00"),# rank 2 lex
        ]
        vec = [
            _hit("cand-both", "skills_00"), # rank 1 vec
            _hit("cand-vec-only", "exp_00"),# rank 2 vec
        ]
        results = fuse_results(lex, vec, final_top_k=10)
        scores = {r.candidate_id: r.rrf_score for r in results}
        assert scores["cand-both"] > scores["cand-lex-only"]
        assert scores["cand-both"] > scores["cand-vec-only"]

    def test_results_sorted_by_score_descending(self):
        lex = [_hit(f"cand-{i}", "exp_00") for i in range(5)]
        results = fuse_results(lex, [], final_top_k=10)
        scores = [r.rrf_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_higher_rank_beats_lower_rank(self):
        """rank-1 candidate must outscore rank-2 candidate (same single method)."""
        lex = [_hit("cand-a", "exp_00"), _hit("cand-b", "exp_00")]
        results = fuse_results(lex, [], final_top_k=10)
        a = next(r for r in results if r.candidate_id == "cand-a")
        b = next(r for r in results if r.candidate_id == "cand-b")
        assert a.rrf_score > b.rrf_score


# ─── RRF determinism ──────────────────────────────────────────────────────────

class TestDeterminism:

    def test_same_input_same_output(self):
        lex = [_hit("cand-a", "exp_00"), _hit("cand-b", "skills_00")]
        vec = [_hit("cand-b", "exp_00"), _hit("cand-c", "edu_00")]
        r1 = fuse_results(lex, vec, final_top_k=10)
        r2 = fuse_results(lex, vec, final_top_k=10)
        assert [p.candidate_id for p in r1] == [p.candidate_id for p in r2]
        assert [p.rrf_score for p in r1] == [p.rrf_score for p in r2]
