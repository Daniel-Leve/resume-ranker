"""
Phase 3 configuration.

Reads from the environment variables (or .env).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ─── MongoDB Atlas ─────────────────────────────────────────────────────────────
MONGODB_URI: str = os.getenv("MONGODB_URI", "")
MONGODB_DATABASE: str = os.getenv("MONGODB_DATABASE", "resume_screening")
MONGODB_COLLECTION: str = os.getenv("MONGODB_COLLECTION", "candidate_chunks")

# ─── Voyage AI ─────────────────────────────────────────────────────────────────
VOYAGE_API_KEY: str = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_RERANK_MODEL: str = os.getenv("VOYAGE_RERANK_MODEL", "rerank-2.5")

# ─── Reranking Parameters ──────────────────────────────────────────────────────
# -1 means rerank all candidates passed from Phase 2
_rerank_top_k_str = os.getenv("RERANK_TOP_K", "-1")
RERANK_TOP_K: int = int(_rerank_top_k_str) if _rerank_top_k_str.strip() else -1

# Maximum document length to send to Voyage reranker to avoid token limits
# rerank-2.5 has a context length of 16,000 tokens. A conservative 12,000 tokens
# is roughly 48,000 characters. We'll set a default char limit to be safe.
RERANK_MAX_DOCUMENT_CHARS: int = int(os.getenv("RERANK_MAX_DOCUMENT_CHARS", "30000"))


def validate() -> None:
    """Validate required environment variables."""
    missing = []
    if not VOYAGE_API_KEY:
        missing.append("VOYAGE_API_KEY")
    if not MONGODB_URI:
        missing.append("MONGODB_URI")
    
    if missing:
        raise EnvironmentError(
            f"Required environment variables not set: {', '.join(missing)}. "
            "Please configure them in your .env file."
        )
