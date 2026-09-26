"""
Phase 2 semantic retrieval via MongoDB Atlas Vector Search.

Uses the ``$vectorSearch`` aggregation stage (cosine similarity) against the
1024-dimensional Voyage AI embeddings stored in the ``embedding`` field of
every candidate chunk document.

Prerequisites
-------------
An Atlas Vector Search index named ``config.VECTOR_INDEX_NAME`` must exist on
the ``candidate_chunks`` collection **before** this module is called.
The index must be configured for:
    path            : embedding
    numDimensions   : 1024
    similarity      : cosine

See ``phase2/README.md → MongoDB Atlas Index Setup`` for step-by-step
instructions to create it in the Atlas web UI.

The ``$vectorSearch`` stage MUST be the first stage in the pipeline.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from pymongo.collection import Collection

from phase2 import config
from phase2.retrieval.lexical_search import ChunkHit  # re-use the same NamedTuple

logger = logging.getLogger(__name__)


def vector_search(
    collection: Collection,
    query_embedding: List[float],
    top_k: Optional[int] = None,
) -> List[ChunkHit]:
    """
    Run semantic retrieval using MongoDB Atlas Vector Search.

    The ``query_embedding`` MUST have been produced with:
        ``embed_texts([jd_text], input_type="query")``
    using the **same** model (voyage-4-large) as was used during indexing.

    Args:
        collection:      MongoDB collection containing candidate chunks.
        query_embedding: 1024-float job-description query vector.
        top_k:           Max chunk hits to return (defaults to ``config.VECTOR_TOP_K``).

    Returns:
        Ordered list of ChunkHit, best cosine similarity first.

    Raises:
        ValueError:   If query_embedding has wrong dimensionality.
        RuntimeError: If the Atlas Vector Search index does not exist.
    """
    k = top_k if top_k is not None else config.VECTOR_TOP_K

    if len(query_embedding) != config.VOYAGE_EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"query_embedding has {len(query_embedding)} dimensions, "
            f"expected {config.VOYAGE_EMBEDDING_DIMENSIONS}. "
            "Ensure the query was embedded with the same model used during indexing."
        )

    # numCandidates must be >= limit; MongoDB recommends 10-20× for good recall.
    # Cap at 10 000 to avoid over-scanning a small free-tier collection.
    num_candidates = min(k * 10, 10_000)

    pipeline = [
        {
            "$vectorSearch": {
                "index": config.VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": num_candidates,
                "limit": k,
            }
        },
        {
            # Materialise the vector similarity score for downstream logging/debug.
            "$addFields": {"_vec_score": {"$meta": "vectorSearchScore"}}
        },
        {
            "$project": {
                "_id": 0,
                "candidate_id": 1,
                "chunk_id": 1,
                "section": 1,
                "source_key": 1,
                "_vec_score": 1,
            }
        },
    ]

    try:
        results = list(collection.aggregate(pipeline))
    except Exception as exc:
        _msg = str(exc).lower()
        if "index not found" in _msg or "indexnotfound" in _msg or "no such index" in _msg:
            raise RuntimeError(
                f"Atlas Vector Search index '{config.VECTOR_INDEX_NAME}' not found on "
                f"collection '{collection.name}'. Create it in the Atlas UI — "
                "see phase2/README.md."
            ) from exc
        raise

    logger.info("Vector search: %d chunk hits (top_k=%d)", len(results), k)
    return [
        ChunkHit(
            candidate_id=r["candidate_id"],
            chunk_id=r["chunk_id"],
            section=r.get("section", "unknown"),
            source_key=r.get("source_key", ""),
        )
        for r in results
    ]
