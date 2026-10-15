"""
Phase 4 Privacy and PII Redaction Module.
Ensures resumes are sanitized before submission to external LLMs.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from phase4 import config

logger = logging.getLogger(__name__)

# ── Regex Patterns for Sensitive Data ────────────────────────────────────────

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

PHONE_PATTERN = re.compile(
    r"(?:(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,5}[-.\s]?\d{3,5}(?:[-.\s]?\d{1,4})?)"
)

# Refined phone match to avoid stripping normal dates/numbers
def _is_valid_phone(match_text: str) -> bool:
    digits = re.sub(r"\D", "", match_text)
    return 7 <= len(digits) <= 15 and not (len(digits) == 4 and match_text.isdigit())

URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:linkedin\.com|github\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|medium\.com|kaggle\.com|gitlab\.com)[^\s,)>]+"
    r"|https?://[^\s,)>]+"
    r"|(?:linkedin\.com/in/[A-Za-z0-9_-]+|github\.com/[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

DOB_PATTERN = re.compile(
    r"\b(?:DOB|Date of Birth|Birth Date|Birthdate|Age)[:\s]+[^\n,;|]+",
    re.IGNORECASE,
)

GENDER_PATTERN = re.compile(
    r"\b(?:Gender|Sex)[:\s]+(?:Male|Female|Non-binary|Transgender|Cisgender|Other)\b",
    re.IGNORECASE,
)

PHOTO_PATTERN = re.compile(
    r"\b(?:\[?(?:Photo|Headshot|Picture|Image)(?:\s+attached|\s+here)?\]?)",
    re.IGNORECASE,
)

ADDRESS_PATTERN = re.compile(
    r"\b(?:\d{1,5}\s+[A-Za-z0-9\s.,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Circle|Cir)\b"
    r"|Address[:\s]+[^\n]+)",
    re.IGNORECASE,
)


@dataclass
class RedactionResult:
    redacted_text: str
    original_candidate_id: str
    masked_candidate_id: str
    pii_counts: Dict[str, int] = field(default_factory=dict)


class PIIRedactor:
    """Redacts PII from resume text while maintaining candidate pseudonym mapping."""

    def __init__(self, enabled: bool = config.REDACT_PII) -> None:
        self.enabled = enabled
        self._mask_to_orig: Dict[str, str] = {}
        self._orig_to_mask: Dict[str, str] = {}
        self._counter: int = 1

        if not self.enabled:
            logger.warning("PIIRedactor is initialized in DISABLED mode. PII will not be scrubbed.")

    def get_masked_id(self, original_id: str) -> str:
        """Get or assign an anonymous pseudonym for a candidate."""
        if original_id not in self._orig_to_mask:
            masked = f"cand_masked_{self._counter:04d}"
            self._counter += 1
            self._orig_to_mask[original_id] = masked
            self._mask_to_orig[masked] = original_id
        return self._orig_to_mask[original_id]

    def resolve_candidate_id(self, masked_id: str) -> str:
        """Resolve an anonymous pseudonym back to the original candidate ID."""
        return self._mask_to_orig.get(masked_id, masked_id)

    def redact(
        self,
        text: str,
        candidate_id: str,
        candidate_name: Optional[str] = None,
    ) -> RedactionResult:
        """
        Redact personal identifying information from raw resume text.

        Args:
            text: Raw resume text.
            candidate_id: Original candidate/application ID.
            candidate_name: Known candidate full name if available.

        Returns:
            RedactionResult containing sanitized text and mapping information.
        """
        masked_id = self.get_masked_id(candidate_id)

        if not self.enabled:
            return RedactionResult(
                redacted_text=text,
                original_candidate_id=candidate_id,
                masked_candidate_id=masked_id,
                pii_counts={"disabled": 1},
            )

        sanitized = text
        counts: Dict[str, int] = {}

        # 1. Redact Candidate Name if provided or obvious on top lines
        if candidate_name and candidate_name.strip():
            name_parts = candidate_name.strip().split()
            # Redact full name
            pattern = re.compile(re.escape(candidate_name.strip()), re.IGNORECASE)
            sanitized, c = pattern.subn("[NAME_REDACTED]", sanitized)
            if c:
                counts["name"] = counts.get("name", 0) + c
            # Also redact individual first/last if len >= 4
            for part in name_parts:
                if len(part) >= 4:
                    p = re.compile(rf"\b{re.escape(part)}\b", re.IGNORECASE)
                    sanitized, sub_c = p.subn("[NAME_REDACTED]", sanitized)
                    if sub_c:
                        counts["name"] = counts.get("name", 0) + sub_c

        # 2. Redact Emails
        sanitized, c = EMAIL_PATTERN.subn("[EMAIL_REDACTED]", sanitized)
        if c:
            counts["email"] = c

        # 3. Redact Social URLs / Links
        sanitized, c = URL_PATTERN.subn("[URL_REDACTED]", sanitized)
        if c:
            counts["url"] = c

        # 4. Redact Phone Numbers
        def _replace_phone(m: re.Match[str]) -> str:
            raw = m.group(0)
            if _is_valid_phone(raw):
                counts["phone"] = counts.get("phone", 0) + 1
                return "[PHONE_REDACTED]"
            return raw

        sanitized = PHONE_PATTERN.sub(_replace_phone, sanitized)

        # 5. Redact DOB / Age
        sanitized, c = DOB_PATTERN.subn("[DOB_REDACTED]", sanitized)
        if c:
            counts["dob"] = c

        # 6. Redact Gender
        sanitized, c = GENDER_PATTERN.subn("[GENDER_REDACTED]", sanitized)
        if c:
            counts["gender"] = c

        # 7. Redact Photo References
        sanitized, c = PHOTO_PATTERN.subn("[PHOTO_REDACTED]", sanitized)
        if c:
            counts["photo"] = c

        # 8. Redact Physical Address
        sanitized, c = ADDRESS_PATTERN.subn("[ADDRESS_REDACTED]", sanitized)
        if c:
            counts["address"] = c

        return RedactionResult(
            redacted_text=sanitized,
            original_candidate_id=candidate_id,
            masked_candidate_id=masked_id,
            pii_counts=counts,
        )


def sanitize_candidate_feedback(feedback_text: str) -> str:
    """
    Sanitizes candidate feedback markdown text to ensure it never exposes
    internal scores, ranks, rubric weights, or recruiter-only evaluations.
    """
    if not feedback_text or not feedback_text.strip():
        return ""

    text = feedback_text
    # Remove internal score mentions (e.g. "score: 0.8", "score was 0.72", "relevance = 0.9")
    text = re.sub(r"(?i)\b(?:score|relevance|weighted_score|rerank_score)\s*(?:was|is|:|:=|=)?\s*\d+(?:\.\d+)?%?", "", text)
    # Remove internal rank mentions (e.g. "rank #4", "ranked 5th", "rank was 2")
    text = re.sub(r"(?i)\b(?:rank|ranked)\s*(?:#|pos(?:ition)?\.?|was|is)?\s*\d+\b", "", text)
    # Remove rubric weight mentions (e.g. "weight 0.25", "weight: 20%")
    text = re.sub(r"(?i)\b(?:weight|weights)\s*(?:was|is|:|:=|=)?\s*\d+(?:\.\d+)?%?", "", text)
    # Remove any leaked interview question sections
    text = re.sub(r"(?is)##\s*Suggested Interview Questions.*?(?=\n##|\Z)", "", text)
    # Clean up empty sentence fragments
    text = re.sub(r"(?i)\b(?:Your|The)\s+and\s+(?:with)?\s*\.?", "", text)
    # Clean multiple consecutive blank lines and redundant spaces
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text
