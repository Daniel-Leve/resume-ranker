"""
Voyage AI Reranker Client Wrapper.
"""
from __future__ import annotations

import logging
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
) -> List[dict]:
    """
    Call Voyage AI to rerank a list of documents against a query.

    Args:
        query:     The Job Description text.
        documents: A list of candidate resume texts.
        model:     The reranking model to use (default from config).
        top_k:     Number of results to return. If None, returns all.

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

    # The Voyage Rerank API takes list of docs and returns RerankingObject
    # with a `.results` list of RerankingResult elements containing `index` and `relevance_score`.
    # To handle large candidate pools safely while respecting rate limits/batch size:
    # We will just pass them all in one call since Voyage can typically handle 
    # hundreds of docs in one rerank request, depending on token limits.
    # If the user has 100 docs, one request is fine.
    
    try:
        reranking = client.rerank(
            query=query,
            documents=documents,
            model=model,
            top_k=top_k,
        )
    except Exception as exc:
        logger.error("Voyage Rerank API call failed: %s", exc)
        raise

    results = []
    for r in reranking.results:
        results.append({
            "index": r.index,
            "relevance_score": r.relevance_score,
            "document": r.document,
        })
        
    logger.info("Voyage Rerank successful. Returned %d results.", len(results))
    return results
