"""
Voyage AI Reranker Client Wrapper.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

import voyageai

from phase3 import config

logger = logging.getLogger(__name__)


def _get_client() -> voyageai.Client:
    """Create a Voyage AI client."""
    if not config.VOYAGE_API_KEY:
        raise EnvironmentError(
            "VOYAGE_API_KEY is not set in environment or .env file."
        )
    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


def rerank_documents(
    query: str,
    documents: List[str],
    model: Optional[str] = None,
    top_k: Optional[int] = None,
    max_retries: int = 3,
    base_delay_s: float = 2.0,
) -> List[dict]:
    """
    Call Voyage AI to rerank a list of documents against a query with retry on transient errors.

    Args:
        query:        The Job Description text.
        documents:    A list of candidate resume texts.
        model:        The reranking model to use (default from config).
        top_k:        Number of results to return. If None, returns all.
        max_retries:  Maximum attempts on transient failure.
        base_delay_s: Initial backoff delay in seconds.

    Returns:
        List of dicts representing the reranking results, preserving original index.
        Each dict has 'index', 'relevance_score', and 'document'.
    """
    if not query or not query.strip():
        raise ValueError("Query (Job Description) cannot be empty.")
    if not documents:
        return []

    model = model or config.VOYAGE_RERANK_MODEL

    logger.info(
        "Calling Voyage Rerank API (model=%s) for %d documents...",
        model, len(documents)
    )

    client = _get_client()

    reranking = None
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            reranking = client.rerank(
                query=query,
                documents=documents,
                model=model,
                top_k=top_k,
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay_s * (2 ** (attempt - 1))
                logger.warning(
                    "Voyage Rerank API attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt, max_retries, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Voyage Rerank API failed after %d attempts: %s",
                    max_retries, exc,
                )
                raise RuntimeError(
                    f"Voyage rerank failed after {max_retries} attempts: {exc}"
                ) from last_exc

    results = []
    for r in reranking.results:
        results.append({
            "index": r.index,
            "relevance_score": r.relevance_score,
            "document": r.document,
        })
        
    logger.info("Voyage Rerank successful. Returned %d results.", len(results))
    return results
