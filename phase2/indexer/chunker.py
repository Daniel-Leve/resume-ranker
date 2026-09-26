"""
Phase 2 deterministic resume chunker.

Strategy
--------
1. Extract ordered (line_text, page_number) pairs from the Textract ``blocks``
   array included in every Phase 1 extracted JSON.
2. Scan the resume's ``text`` field line-by-line and detect section headers
   using a curated regex pattern list.
3. Accumulate lines under each section and emit a chunk per section.
4. Split sections that exceed ``MAX_CHUNK_CHARS`` at line boundaries.
5. Fall back to fixed-size sliding-window chunking for plain resumes that
   have no recognisable section headers.

Design goals
------------
- Deterministic: same input → same chunk_ids every run.
- No LLM calls: purely regex + line structure from Textract.
- Low cost: avoids excessive overlap / over-chunking.
- Traceable: every chunk carries candidate_id, chunk_id, section, page info,
  and the originating S3 source_key.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ─── Section header patterns ───────────────────────────────────────────────────
# Order matters: more specific patterns first.
# Each tuple is (compiled regex, canonical section label).
# The regex must match the ENTIRE stripped line (anchored).

_SECTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Summary / Objective
    (re.compile(
        r"^(PROFILE|PROFILE\s+SUMMARY|SUMMARY|PROFESSIONAL\s+SUMMARY|EXECUTIVE\s+SUMMARY|"
        r"CAREER\s+SUMMARY|OBJECTIVE|CAREER\s+OBJECTIVE|ABOUT\s+ME|OVERVIEW)\s*$",
        re.IGNORECASE,
    ), "summary"),

    # Skills
    (re.compile(
        r"^(SKILLS?|TECHNICAL\s+SKILLS?|CORE\s+COMPETENCIES|KEY\s+SKILLS?|"
        r"TECHNOLOGIES|TECH\s+STACK|TOOLS?\s*(&|AND)\s*TECHNOLOGIES?|"
        r"TECHNICAL\s+EXPERTISE|AREAS?\s+OF\s+EXPERTISE)\s*$",
        re.IGNORECASE,
    ), "skills"),

    # Experience
    (re.compile(
        r"^(EXPERIENCE|WORK\s+EXPERIENCE|PROFESSIONAL\s+EXPERIENCE|"
        r"EMPLOYMENT(\s+HISTORY)?|WORK\s+HISTORY|JOB\s+HISTORY|"
        r"CAREER\s+HISTORY|RELEVANT\s+EXPERIENCE)\s*$",
        re.IGNORECASE,
    ), "experience"),

    # Projects
    (re.compile(
        r"^(PROJECTS?|PERSONAL\s+PROJECTS?|ACADEMIC\s+PROJECTS?|"
        r"NOTABLE\s+PROJECTS?|OPEN\s+SOURCE|PORTFOLIO)\s*$",
        re.IGNORECASE,
    ), "projects"),

    # Education
    (re.compile(
        r"^(EDUCATION|ACADEMIC\s+BACKGROUND|ACADEMIC\s+QUALIFICATIONS?|"
        r"EDUCATIONAL\s+BACKGROUND|QUALIFICATIONS?)\s*$",
        re.IGNORECASE,
    ), "education"),

    # Certifications
    (re.compile(
        r"^(CERTIFICATIONS?|LICENSES?|PROFESSIONAL\s+CERTIFICATIONS?|"
        r"CREDENTIALS?|COURSES?\s*&?\s*CERTIFICATIONS?)\s*$",
        re.IGNORECASE,
    ), "certifications"),

    # Achievements / Awards
    (re.compile(
        r"^(ACHIEVEMENTS?|AWARDS?|HONORS?|ACCOMPLISHMENTS?|RECOGNITIONS?|"
        r"ACCOLADES?)\s*$",
        re.IGNORECASE,
    ), "achievements"),

    # Publications / Research
    (re.compile(
        r"^(PUBLICATIONS?|RESEARCH|PAPERS?|ARTICLES?|PATENTS?)\s*$",
        re.IGNORECASE,
    ), "publications"),

    # Languages (spoken)
    (re.compile(r"^(LANGUAGES?)\s*$", re.IGNORECASE), "languages"),

    # Volunteer
    (re.compile(
        r"^(VOLUNTEER(ING)?|COMMUNITY\s+SERVICE|SOCIAL\s+WORK|"
        r"EXTRA.?CURRICULAR)\s*$",
        re.IGNORECASE,
    ), "volunteer"),

    # Interests / Hobbies
    (re.compile(
        r"^(INTERESTS?|HOBBIES|ACTIVITIES)\s*$",
        re.IGNORECASE,
    ), "interests"),
]

# Characters per chunk before we split.  ~1200 chars ≈ 300 tokens for voyage-4-large.
_DEFAULT_MAX_CHUNK_CHARS: int = 1200

# Fallback fixed-size parameters (used when no section headers are found)
_FALLBACK_CHUNK_CHARS: int = 1000
_FALLBACK_OVERLAP_CHARS: int = 100


# ─── Public dataclass ──────────────────────────────────────────────────────────

@dataclass
class TextChunk:
    """A single section chunk produced by the chunker."""
    candidate_id: str
    chunk_id: str       # e.g. "john-doe_experience_01"
    source_key: str     # e.g. "extracted/<textract-job-id>.json"
    chunk_index: int    # 0-based index within this candidate
    section: str        # e.g. "experience"
    text: str           # The actual chunk text
    page_start: int     # First page this chunk's lines appear on
    page_end: int       # Last page this chunk's lines appear on


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _detect_section(line: str) -> Optional[str]:
    """Return the canonical section label if ``line`` is a header, else None."""
    stripped = line.strip()
    if not stripped:
        return None
    for pattern, label in _SECTION_PATTERNS:
        if pattern.match(stripped):
            return label
    return None


def _extract_line_pages(blocks: List[dict]) -> List[Tuple[str, int]]:
    """Return ordered (line_text, page_number) pairs from Textract blocks."""
    return [
        (block["Text"], block.get("Page", 1))
        for block in blocks
        if block.get("BlockType") == "LINE" and "Text" in block
    ]


def _build_page_map(line_pages: List[Tuple[str, int]]) -> Dict[str, int]:
    """
    Map each unique line text to its first-occurrence page number.

    When duplicate lines exist (e.g. repeated bullets), we keep the first page,
    which is conservative and avoids false high page numbers.
    """
    mapping: Dict[str, int] = {}
    for text, page in line_pages:
        if text not in mapping:
            mapping[text] = page
    return mapping


def _page_range(lines: List[str], page_map: Dict[str, int]) -> Tuple[int, int]:
    """Return (page_start, page_end) for a collection of lines."""
    pages = [page_map.get(line.strip(), 1) for line in lines if line.strip()]
    if not pages:
        return 1, 1
    return min(pages), max(pages)


def _make_chunk_id(candidate_id: str, section: str, occurrence: int) -> str:
    """Build a deterministic, filesystem-safe chunk_id."""
    return f"{candidate_id}_{section}_{occurrence:02d}"


def _split_section(
    lines: List[str],
    section: str,
    candidate_id: str,
    source_key: str,
    start_chunk_index: int,
    start_occurrence: int,
    page_map: Dict[str, int],
    max_chars: int,
) -> List[TextChunk]:
    """
    Split a single large section into multiple sub-chunks at line boundaries.
    Returns list of TextChunk objects.
    """
    chunks: List[TextChunk] = []
    current_lines: List[str] = []
    current_chars: int = 0
    sub_occ: int = start_occurrence

    def _emit() -> None:
        nonlocal sub_occ
        text = "\n".join(current_lines).strip()
        if not text:
            return
        ps, pe = _page_range(current_lines, page_map)
        chunk_index = start_chunk_index + len(chunks)
        chunks.append(TextChunk(
            candidate_id=candidate_id,
            chunk_id=_make_chunk_id(candidate_id, section, sub_occ),
            source_key=source_key,
            chunk_index=chunk_index,
            section=section,
            text=text,
            page_start=ps,
            page_end=pe,
        ))
        sub_occ += 1

    for line in lines:
        line_cost = len(line) + 1  # +1 for the newline character
        if current_lines and current_chars + line_cost > max_chars:
            _emit()
            current_lines = [line]
            current_chars = line_cost
        else:
            current_lines.append(line)
            current_chars += line_cost

    if current_lines:
        _emit()

    return chunks


def _fallback_chunks(
    text: str,
    candidate_id: str,
    source_key: str,
) -> List[TextChunk]:
    """
    Fixed-size fallback chunker.

    Used when no section headers are found. Splits at ``_FALLBACK_CHUNK_CHARS``
    characters with ``_FALLBACK_OVERLAP_CHARS`` overlap to preserve continuity.
    All chunks are labelled section='unknown'.
    """
    chunks: List[TextChunk] = []
    chunk_index: int = 0
    start: int = 0

    while start < len(text):
        end = min(start + _FALLBACK_CHUNK_CHARS, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(TextChunk(
                candidate_id=candidate_id,
                chunk_id=_make_chunk_id(candidate_id, "chunk", chunk_index),
                source_key=source_key,
                chunk_index=chunk_index,
                section="unknown",
                text=chunk_text,
                page_start=1,
                page_end=1,
            ))
            chunk_index += 1
        # Advance with overlap so consecutive chunks share context
        next_start = end - _FALLBACK_OVERLAP_CHARS
        start = next_start if next_start > start else end  # prevent infinite loop

    return chunks


# ─── Public API ───────────────────────────────────────────────────────────────

def chunk_resume(
    candidate_id: str,
    source_key: str,
    text: str,
    blocks: Optional[List[dict]] = None,
    max_chars: int = _DEFAULT_MAX_CHUNK_CHARS,
) -> List[TextChunk]:
    """
    Deterministically chunk a Phase 1 resume into section-aware pieces.

    Args:
        candidate_id:  Human-readable ID derived from the PDF filename.
        source_key:    S3 key of the Phase 1 extracted JSON (for traceability).
        text:          The ``text`` field from the Phase 1 JSON (newline-joined
                       Textract LINE blocks).
        blocks:        The ``blocks`` array from Phase 1 JSON (for page numbers).
                       Optional — if omitted, all pages default to 1.
        max_chars:     Maximum characters per chunk before splitting.

    Returns:
        List of TextChunk objects, ordered by chunk_index.
    """
    if not text or not text.strip():
        return []

    # Build line→page mapping from Textract blocks
    page_map: Dict[str, int] = {}
    if blocks:
        line_pages = _extract_line_pages(blocks)
        page_map = _build_page_map(line_pages)

    # ── Pass 1: Group lines into sections ──────────────────────────────────────
    sections: List[Tuple[str, List[str]]] = []  # [(label, [lines])]
    current_section: str = "header"
    current_lines: List[str] = []

    for line in text.split("\n"):
        detected = _detect_section(line)
        if detected is not None:
            if current_lines:
                sections.append((current_section, current_lines))
            current_section = detected
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_section, current_lines))

    # ── Fallback when no named sections detected ───────────────────────────────
    named_sections = [s for s, _ in sections if s != "header"]
    if not named_sections:
        return _fallback_chunks(text, candidate_id, source_key)

    # ── Pass 2: Build chunks, splitting large sections ─────────────────────────
    all_chunks: List[TextChunk] = []
    # Track per-section occurrence counter so chunk_ids are always unique
    section_occurrence: Dict[str, int] = defaultdict(int)

    for section_label, section_lines in sections:
        joined = "\n".join(section_lines).strip()
        if not joined:
            continue

        occ = section_occurrence[section_label]
        start_chunk_index = len(all_chunks)

        if len(joined) <= max_chars:
            # Single chunk for this section pass
            ps, pe = _page_range(section_lines, page_map)
            all_chunks.append(TextChunk(
                candidate_id=candidate_id,
                chunk_id=_make_chunk_id(candidate_id, section_label, occ),
                source_key=source_key,
                chunk_index=start_chunk_index,
                section=section_label,
                text=joined,
                page_start=ps,
                page_end=pe,
            ))
            section_occurrence[section_label] += 1
        else:
            # Split large section
            sub_chunks = _split_section(
                lines=section_lines,
                section=section_label,
                candidate_id=candidate_id,
                source_key=source_key,
                start_chunk_index=start_chunk_index,
                start_occurrence=occ,
                page_map=page_map,
                max_chars=max_chars,
            )
            all_chunks.extend(sub_chunks)
            section_occurrence[section_label] += len(sub_chunks)

    return all_chunks


def compute_content_hash(text: str) -> str:
    """
    Compute a SHA-256 hash of the normalised resume text.

    Used for idempotent re-indexing: if this hash matches what is already
    stored in MongoDB, the resume has not changed and re-embedding is skipped.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
