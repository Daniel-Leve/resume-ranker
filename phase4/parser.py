"""
Job Description Parser and Requirement Extractor.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from phase4.models import JobRequirement

# Common filler words to ignore when extracting keywords from requirements
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "as", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "can", "could", "should", "would", "may",
    "might", "must", "will", "shall", "years", "year", "plus", "experience", "strong",
    "knowledge", "understanding", "proficiency", "solid", "familiarity", "professional",
    "working", "skills", "ability", "excellent", "good", "hands-on", "demonstrated",
    "proven", "similar", "such", "other", "etc", "using", "used", "role", "team",
    "looking", "responsibilities", "required", "preferred", "nice", "about"
}

# Regex to detect common JD section headers
REQUIRED_HEADERS = re.compile(
    r"^(required|minimum|basic|must\s+have|requirements|what\s+you('ll|\s+will)\s+need)",
    re.IGNORECASE,
)
PREFERRED_HEADERS = re.compile(
    r"^(preferred|nice\s+to\s+have|bonus|desired|plus|optional)",
    re.IGNORECASE,
)
RESPONSIBILITIES_HEADERS = re.compile(
    r"^(responsibilities|what\s+you('ll|\s+will)\s+do|duties|core\s+responsibilities)",
    re.IGNORECASE,
)


def extract_keywords_from_text(text: str) -> List[str]:
    """
    Extract meaningful technical and domain keywords/phrases from a requirement string.
    Preserves compound names like 'Spring Boot', 'PostgreSQL', 'CI/CD', 'RESTful APIs', etc.
    """
    keywords: List[str] = []

    # 1. Look for technology terms in parentheses or quotes: (Spring MVC, Spring Data JPA)
    paren_matches = re.findall(r"\(([^)]+)\)", text)
    for p in paren_matches:
        for part in re.split(r"[,;:/]", p):
            cleaned = part.strip()
            if cleaned and len(cleaned) > 1 and cleaned.lower() not in STOPWORDS:
                keywords.append(cleaned)

    # 2. Look for acronyms or capitalized tech terms (e.g. AWS, CI/CD, SQL, REST, Docker)
    tech_patterns = re.findall(
        r"\b([A-Z][a-zA-Z0-9_\-\+\#]+(?:\s+[A-Z][a-zA-Z0-9_\-\+\#]+)*|[A-Z]{2,}(?:/[A-Z]{2,})?)\b",
        text,
    )
    for term in tech_patterns:
        cleaned = term.strip()
        if cleaned.lower() not in STOPWORDS and len(cleaned) > 1:
            keywords.append(cleaned)

    # 3. Look for lowercase words with special chars like c++, c#, .net
    special_tech = re.findall(r"\b(c\+\+|c\#|\.net|node\.js|vue\.js|react\.js)\b", text, re.IGNORECASE)
    for term in special_tech:
        keywords.append(term.strip())

    # 4. Extract standard alphanumeric words that are not stopwords
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9\-\+\#]{2,}\b", text)
    for w in words:
        if w.lower() not in STOPWORDS:
            keywords.append(w)

    # Deduplicate while preserving order, case-insensitive
    seen = set()
    deduped: List[str] = []
    for kw in keywords:
        low = kw.lower()
        if low not in seen:
            seen.add(low)
            deduped.append(kw)

    return deduped


def parse_job_requirements(jd_text: str) -> List[JobRequirement]:
    """
    Parse a job description into a structured list of JobRequirements.
    Detects sections (Required, Nice to have, Responsibilities) and individual bullet points.
    """
    if not jd_text or not jd_text.strip():
        return []

    lines = [line.strip() for line in jd_text.splitlines()]
    requirements: List[JobRequirement] = []

    current_category = "required"
    bullet_pattern = re.compile(r"^[-*•]\s*(.*)$")
    numbered_pattern = re.compile(r"^\d+[\.\)]\s*(.*)$")

    for line in lines:
        if not line or line.startswith("---") or line.startswith("==="):
            continue

        clean_header = line.rstrip(":-")
        # Check if line is a header
        if REQUIRED_HEADERS.search(clean_header):
            current_category = "required"
            continue
        elif PREFERRED_HEADERS.search(clean_header):
            current_category = "preferred"
            continue
        elif RESPONSIBILITIES_HEADERS.search(clean_header):
            current_category = "general"
            continue

        # Check for bullet point
        bullet_match = bullet_pattern.match(line) or numbered_pattern.match(line)
        if bullet_match:
            item_text = bullet_match.group(1).strip()
            if item_text:
                kws = extract_keywords_from_text(item_text)
                requirements.append(
                    JobRequirement(text=item_text, category=current_category, keywords=kws)
                )
        elif len(line) > 25 and not line.endswith(":") and ("experience" in line.lower() or "knowledge" in line.lower() or "skills" in line.lower()):
            # A stand-alone requirement sentence
            kws = extract_keywords_from_text(line)
            requirements.append(
                JobRequirement(text=line, category=current_category, keywords=kws)
            )

    # Fallback: if no bullet items were detected (e.g. freeform paragraph), extract key non-empty sentences
    if not requirements:
        sentences = re.split(r"(?<=[.!?])\s+", jd_text)
        for sent in sentences:
            s = sent.strip()
            if len(s) > 20:
                kws = extract_keywords_from_text(s)
                if kws:
                    requirements.append(
                        JobRequirement(text=s, category="general", keywords=kws)
                    )

    return requirements
