"""
Phase 4 Configuration and Constants.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv(Path(__file__).parent.parent / ".env")

EXPLANATION_VERSION = "1.0.0"

# MongoDB Defaults
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "resumes")
MONGODB_COLLECTION = os.environ.get("MONGODB_COLLECTION", "candidate_chunks")

# Evidence formatting limits
MAX_EXCERPT_CHARS = int(os.environ.get("PHASE4_MAX_EXCERPT_CHARS", "250"))
MAX_EVIDENCE_PER_REQ = int(os.environ.get("PHASE4_MAX_EVIDENCE_PER_REQ", "3"))

# Standard disclaimers and limitations
AUDIT_LIMITATIONS = [
    "Explanations reflect only the resume chunks retrieved and evaluated in Phases 2 and 3, not the full un-chunked resume or full candidate background.",
    "Reranker rank reflects overall semantic relevance to the job description, not an isolated sum or arithmetic score of individual requirements.",
    "Unestablished requirements indicate absence of direct evidence in retrieved resume chunks, not confirmed lack of candidate qualification.",
    "No protected personal characteristics (e.g. age, gender, ethnicity) are evaluated or utilized in ranking or explainability."
]
