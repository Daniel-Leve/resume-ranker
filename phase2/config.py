"""
Phase 2 configuration.

All secrets are read from environment variables (or a .env file via python-dotenv).
Never hard-code credentials here. Copy .env.example to .env and fill in your values.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ─── AWS / S3 ──────────────────────────────────────────────────────────────────
# Phase 1 writes extracted JSON to:  s3://<S3_BUCKET_NAME>/<S3_EXTRACTED_PREFIX><job-id>.json

AWS_REGION: str = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "")
S3_EXTRACTED_PREFIX: str = os.getenv("S3_EXTRACTED_PREFIX", "extracted/")

# ─── Voyage AI ─────────────────────────────────────────────────────────────────
# voyage-4-large: 1024-dimensional embeddings, strong multilingual support.
# IMPORTANT: Use input_type="document" for resume chunks,
#            input_type="query"    for job descriptions.

VOYAGE_API_KEY: str = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL: str = os.getenv("VOYAGE_MODEL", "voyage-4-large")
VOYAGE_EMBEDDING_DIMENSIONS: int = int(os.getenv("VOYAGE_EMBEDDING_DIMENSIONS", "1024"))

# Texts per Voyage API call.  Voyage allows up to 128 inputs or ~320K tokens
# per request; 72 is a safe conservative default for variable-length chunks.
VOYAGE_BATCH_SIZE: int = int(os.getenv("VOYAGE_BATCH_SIZE", "72"))

# ─── MongoDB Atlas ─────────────────────────────────────────────────────────────
# Free cluster (M0) supports Atlas Search + Vector Search indexes.
# Database user must have readWrite on MONGODB_DATABASE only.

MONGODB_URI: str = os.getenv("MONGODB_URI", "")
MONGODB_DATABASE: str = os.getenv("MONGODB_DATABASE", "resume_screening")
MONGODB_COLLECTION: str = os.getenv("MONGODB_COLLECTION", "candidate_chunks")

# Atlas index names — must match exactly what you create in the Atlas UI.
# See phase2/README.md → "MongoDB Atlas Index Setup" for step-by-step instructions.
VECTOR_INDEX_NAME: str = os.getenv("VECTOR_INDEX_NAME", "vector_search_index")
TEXT_INDEX_NAME: str = os.getenv("TEXT_INDEX_NAME", "text_search_index")

# ─── Retrieval parameters ──────────────────────────────────────────────────────
# These are development defaults; tune upward as your candidate pool grows.

LEXICAL_TOP_K: int = int(os.getenv("LEXICAL_TOP_K", "15"))
VECTOR_TOP_K: int = int(os.getenv("VECTOR_TOP_K", "15"))
FINAL_TOP_K: int = int(os.getenv("FINAL_TOP_K", "15"))

# RRF smoothing constant k=60 (from the original Cormack et al. 2009 paper).
RRF_K: int = int(os.getenv("RRF_K", "60"))

# ─── Chunking ──────────────────────────────────────────────────────────────────
# Maximum characters per resume chunk before it is split further.
# 1200 chars ≈ 300 tokens, which is well within voyage-4-large's context window.
MAX_CHUNK_CHARS: int = int(os.getenv("MAX_CHUNK_CHARS", "1200"))


# ─── Validation ───────────────────────────────────────────────────────────────

def validate() -> None:
    """
    Raise EnvironmentError if any required environment variable is missing.
    Call this at the top of every CLI entry point.
    """
    missing: list[str] = []
    if not VOYAGE_API_KEY:
        missing.append("VOYAGE_API_KEY")
    if not MONGODB_URI:
        missing.append("MONGODB_URI")
    if not S3_BUCKET_NAME:
        missing.append("S3_BUCKET_NAME")
    if missing:
        raise EnvironmentError(
            f"Required environment variables not set: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your credentials."
        )
