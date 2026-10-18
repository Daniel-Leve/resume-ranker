"""
Phase 4 Configuration and Constants.
Faithful Explainability Layer for AI Resume Screening SaaS.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

EXPLANATION_VERSION = "1.0.0"

# ── Groq LLM Configuration ──────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# ── Free-Tier Rate Limits & Budget ───────────────────────────────────────────
RATE_LIMIT_RPM = int(os.environ.get("PHASE4_RATE_LIMIT_RPM", "30"))
RATE_LIMIT_RPD = int(os.environ.get("PHASE4_RATE_LIMIT_RPD", "1000"))
RATE_LIMIT_TPM = int(os.environ.get("PHASE4_RATE_LIMIT_TPM", "8000"))
RATE_LIMIT_TPD = int(os.environ.get("PHASE4_RATE_LIMIT_TPD", "200000"))
DAILY_BUDGET_STOP_THRESHOLD = float(os.environ.get("PHASE4_BUDGET_STOP_THRESHOLD", "0.90"))

# ── Privacy & PII Redaction ──────────────────────────────────────────────────
REDACT_PII = os.environ.get("REDACT_PII", "true").lower() in ("true", "1", "yes")
if not REDACT_PII:
    logger.warning("WARNING: REDACT_PII is disabled! Personal data may be sent in plaintext.")

# ── Storage Paths (Pure File-Based JSON — Zero SQLite) ────────────────────────
IS_LAMBDA = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("LAMBDA_TASK_ROOT"))
_DEFAULT_BASE_DIR = "/tmp/phase4" if IS_LAMBDA else "."

DATA_DIR = Path(os.environ.get("PHASE4_DATA_DIR", f"{_DEFAULT_BASE_DIR}/data" if IS_LAMBDA else "data"))
BUDGET_FILE = DATA_DIR / "budget_usage.json"
CACHE_DIR = DATA_DIR / "cache"
REVIEW_QUEUE_FILE = DATA_DIR / "review_queue.json"
REVIEW_HISTORY_FILE = DATA_DIR / "review_queue_history.json"

RUBRICS_DIR = Path(os.environ.get("PHASE4_RUBRICS_DIR", f"{_DEFAULT_BASE_DIR}/rubrics" if IS_LAMBDA else "rubrics"))
REPORTS_DIR = Path(os.environ.get("PHASE4_REPORTS_DIR", f"{_DEFAULT_BASE_DIR}/reports" if IS_LAMBDA else "reports"))
FEEDBACK_DIR = Path(os.environ.get("PHASE4_FEEDBACK_DIR", f"{_DEFAULT_BASE_DIR}/feedback" if IS_LAMBDA else "feedback"))

# Ensure local directories exist (safely ignored if read-only filesystem or restricted environment)
for directory in (DATA_DIR, CACHE_DIR, RUBRICS_DIR, REPORTS_DIR, FEEDBACK_DIR):
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create local storage directory %s: %s", directory, exc)

# ── Evidence & Verification Thresholds ───────────────────────────────────────
MAX_EXCERPT_CHARS = int(os.environ.get("PHASE4_MAX_EXCERPT_CHARS", "250"))
MAX_EVIDENCE_PER_REQ = int(os.environ.get("PHASE4_MAX_EVIDENCE_PER_REQ", "3"))
EVIDENCE_FUZZY_THRESHOLD = float(os.environ.get("PHASE4_FUZZY_THRESHOLD", "85.0"))
CONFIDENCE_THRESHOLD = float(os.environ.get("PHASE4_CONFIDENCE_THRESHOLD", "0.60"))

# ── MongoDB Defaults (existing project infrastructure) ──────────────────────
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "resumes")
MONGODB_COLLECTION = os.environ.get("MONGODB_COLLECTION", "candidate_chunks")

# ── Standard Disclaimers ─────────────────────────────────────────────────────
AUDIT_LIMITATIONS = [
    "Explanations reflect only the resume chunks retrieved and evaluated in Phases 2 and 3, not the full un-chunked resume or full candidate background.",
    "Reranker rank reflects overall semantic relevance to the job description, not an isolated sum or arithmetic score of individual requirements.",
    "Unestablished requirements indicate absence of direct evidence in retrieved resume chunks, not confirmed lack of candidate qualification.",
    "No protected personal characteristics (e.g. age, gender, ethnicity) are evaluated or utilized in ranking or explainability."
]
