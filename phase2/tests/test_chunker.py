"""
Unit tests for phase2.indexer.chunker

Tests cover:
- Section header detection
- Section-aware chunking (happy path)
- Large section splitting
- Fallback chunking for plain resumes
- Page metadata propagation from Textract blocks
- Idempotency (same input → same chunk_ids)
- Empty / blank resume handling
- candidate_id derivation
- Content hash stability
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from phase2.indexer.chunker import (
    TextChunk,
    _detect_section,
    chunk_resume,
    compute_content_hash,
)
from phase2.indexer.index_resumes import derive_candidate_id

# ─── Fixtures ─────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture()
def sample_extracted() -> dict:
    return load_fixture("sample_extracted.json")


SIMPLE_TEXT = """\
Jane Smith
jane@example.test | Bangalore

SUMMARY
Python developer with 5 years of experience in data engineering and ETL pipelines.

SKILLS
Python, Apache Spark, Airflow, SQL, dbt, AWS Redshift, Pandas

EXPERIENCE
Data Engineer - DataCo
2022 - Present
Built ETL pipelines processing 10M rows/day using PySpark.
Orchestrated workflows with Apache Airflow DAGs.

EDUCATION
M.Tech, Data Science
IISc Bangalore, 2022
"""


# ─── Section detection ─────────────────────────────────────────────────────────

class TestDetectSection:

    def test_experience_exact(self):
        assert _detect_section("EXPERIENCE") == "experience"

    def test_experience_mixed_case(self):
        assert _detect_section("Work Experience") == "experience"

    def test_experience_professional(self):
        assert _detect_section("Professional Experience") == "experience"

    def test_skills_exact(self):
        assert _detect_section("SKILLS") == "skills"

    def test_skills_technical(self):
        assert _detect_section("Technical Skills") == "skills"

    def test_education_exact(self):
        assert _detect_section("EDUCATION") == "education"

    def test_summary_exact(self):
        assert _detect_section("SUMMARY") == "summary"

    def test_summary_profile(self):
        assert _detect_section("PROFILE") == "summary"

    def test_certifications(self):
        assert _detect_section("CERTIFICATIONS") == "certifications"

    def test_projects(self):
        assert _detect_section("Projects") == "projects"

    def test_achievements(self):
        assert _detect_section("Awards") == "achievements"

    def test_non_header_line(self):
        assert _detect_section("Built REST APIs using Java and Spring Boot") is None

    def test_empty_line(self):
        assert _detect_section("") is None

    def test_whitespace_only(self):
        assert _detect_section("   ") is None

    def test_partial_match_not_detected(self):
        # "Experienced" contains EXPERIENCE but is not a header line
        assert _detect_section("Experienced software engineer") is None

    def test_trailing_whitespace_stripped(self):
        assert _detect_section("SKILLS   ") == "skills"


# ─── Section-aware chunking ────────────────────────────────────────────────────

class TestChunkResume:

    def test_sections_detected(self):
        chunks = chunk_resume("jane-smith", "extracted/abc.json", SIMPLE_TEXT)
        sections = {c.section for c in chunks}
        assert "summary" in sections
        assert "skills" in sections
        assert "experience" in sections
        assert "education" in sections

    def test_no_empty_chunks(self):
        chunks = chunk_resume("jane-smith", "extracted/abc.json", SIMPLE_TEXT)
        for c in chunks:
            assert c.text.strip(), f"Empty chunk: {c.chunk_id}"

    def test_chunk_ids_unique(self):
        chunks = chunk_resume("jane-smith", "extracted/abc.json", SIMPLE_TEXT)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk_ids detected"

    def test_candidate_id_in_all_chunks(self):
        chunks = chunk_resume("jane-smith", "extracted/abc.json", SIMPLE_TEXT)
        for c in chunks:
            assert c.candidate_id == "jane-smith"

    def test_source_key_in_all_chunks(self):
        chunks = chunk_resume("jane-smith", "extracted/abc.json", SIMPLE_TEXT)
        for c in chunks:
            assert c.source_key == "extracted/abc.json"

    def test_chunk_index_sequential(self):
        chunks = chunk_resume("jane-smith", "extracted/abc.json", SIMPLE_TEXT)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_idempotent(self):
        """Same input always produces identical chunk_ids."""
        chunks1 = chunk_resume("cand", "extracted/abc.json", SIMPLE_TEXT)
        chunks2 = chunk_resume("cand", "extracted/abc.json", SIMPLE_TEXT)
        assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]

    def test_empty_text(self):
        chunks = chunk_resume("empty", "extracted/abc.json", "")
        assert chunks == []

    def test_blank_text(self):
        chunks = chunk_resume("blank", "extracted/abc.json", "   \n\n   ")
        assert chunks == []

    def test_fixture_chunks(self, sample_extracted):
        """Chunking the fixture produces sections and no duplicates."""
        data = sample_extracted
        chunks = chunk_resume(
            "john-doe",
            f"extracted/{data['job_id']}.json",
            data["text"],
            data["blocks"],
        )
        assert len(chunks) >= 4  # summary, skills, experience, education, certifications
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))
        sections = {c.section for c in chunks}
        assert "experience" in sections
        assert "education" in sections

    def test_page_metadata_from_blocks(self, sample_extracted):
        """Page metadata is populated from Textract blocks when provided."""
        data = sample_extracted
        chunks = chunk_resume(
            "john-doe",
            f"extracted/{data['job_id']}.json",
            data["text"],
            data["blocks"],
        )
        # Education block is on page 2 in the fixture
        edu_chunks = [c for c in chunks if c.section == "education"]
        assert edu_chunks, "No education chunk found"
        assert edu_chunks[0].page_end >= 2

    def test_no_blocks_defaults_page_1(self):
        chunks = chunk_resume("cand", "extracted/abc.json", SIMPLE_TEXT, blocks=None)
        for c in chunks:
            assert c.page_start == 1
            assert c.page_end == 1


# ─── Large section splitting ───────────────────────────────────────────────────

class TestLargeSectionSplit:

    def test_large_experience_split(self):
        """An experience section exceeding MAX_CHUNK_CHARS is split."""
        long_entry = "Software Engineer at Company\nBuilt scalable systems.\n" * 30
        text = f"SKILLS\nPython, Java\nEXPERIENCE\n{long_entry}EDUCATION\nB.Tech CSE 2020"
        chunks = chunk_resume("cand", "extracted/abc.json", text, max_chars=400)
        exp_chunks = [c for c in chunks if c.section == "experience"]
        assert len(exp_chunks) > 1, "Large experience section should be split"

    def test_split_chunks_ids_unique(self):
        long_entry = "Line of work experience content here.\n" * 40
        text = f"EXPERIENCE\n{long_entry}"
        chunks = chunk_resume("cand", "extracted/abc.json", text, max_chars=300)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))


# ─── Fallback chunking ─────────────────────────────────────────────────────────

class TestFallbackChunking:

    def test_no_headers_uses_fallback(self):
        """A plain-text resume with no section headers uses fallback chunking."""
        text = (
            "Alex Johnson, Developer, alex@example.test\n"
            "Five years of building web applications. "
            "Expert in JavaScript, TypeScript, React, and Node.js. "
            "Previously at Startup X and BigCorp Y. "
        ) * 20  # repeat to exceed single chunk
        chunks = chunk_resume("alex-johnson", "extracted/abc.json", text, max_chars=500)
        assert len(chunks) >= 2
        for c in chunks:
            assert c.section == "unknown"

    def test_fallback_no_empty_chunks(self):
        text = "A" * 2500
        chunks = chunk_resume("cand", "extracted/abc.json", text, max_chars=500)
        for c in chunks:
            assert c.text.strip()


# ─── Content hash ──────────────────────────────────────────────────────────────

class TestContentHash:

    def test_stable(self):
        assert compute_content_hash("hello world") == compute_content_hash("hello world")

    def test_different_inputs_differ(self):
        assert compute_content_hash("foo") != compute_content_hash("bar")

    def test_is_hex_string(self):
        h = compute_content_hash("test")
        assert len(h) == 64
        int(h, 16)  # should not raise


# ─── Candidate ID derivation ───────────────────────────────────────────────────

class TestDeriveCandidateId:

    def test_simple_filename(self):
        assert derive_candidate_id("incoming/john-doe.pdf") == "john-doe"

    def test_spaces_become_hyphens(self):
        assert derive_candidate_id("incoming/Jane Smith.pdf") == "jane-smith"

    def test_underscores_preserved(self):
        result = derive_candidate_id("incoming/c001_alice.pdf")
        assert result == "c001_alice"

    def test_no_directory(self):
        assert derive_candidate_id("john-doe.pdf") == "john-doe"

    def test_no_extension(self):
        assert derive_candidate_id("incoming/john-doe") == "john-doe"

    def test_special_chars_become_hyphens(self):
        result = derive_candidate_id("incoming/john.doe@resume.pdf")
        assert result  # Must be non-empty
        assert "@" not in result

    def test_textract_job_id_fallback(self):
        # When source.key is missing we fall back to the S3 key (textract job id)
        result = derive_candidate_id("extracted/abc123textractjobid.json")
        assert result  # non-empty
