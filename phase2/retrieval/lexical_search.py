"""
Phase 2 lexical (BM25) retrieval via MongoDB Atlas Search.

Uses the ``$search`` aggregation stage with the ``text`` operator, which
applies the Lucene BM25 ranking model to the ``text`` field of every
candidate chunk document.

Prerequisites
-------------
An Atlas Search index named ``config.TEXT_INDEX_NAME`` must exist on the
``candidate_chunks`` collection **before** this module is called.
See ``phase2/README.md → MongoDB Atlas Index Setup`` for step-by-step
instructions to create it in the Atlas web UI.

The ``$search`` stage MUST be the first stage in the aggregation pipeline.
"""
from __future__ import annotations

import logging
from typing import List, NamedTuple, Optional

from pymongo.collection import Collection

from phase2 import config

logger = logging.getLogger(__name__)


class ChunkHit(NamedTuple):
    """
    A single chunk returned by a retrieval method.

    Re-used by both lexical_search and vector_search so that fusion.py
    can accept a uniform list type from either method.
    """
    candidate_id: str
    chunk_id: str
    section: str
    source_key: str


def lexical_search(
    collection: Collection,
    query_text: str,
    top_k: Optional[int] = None,
    tenant_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> List[ChunkHit]:
    """
    Run BM25 lexical retrieval using MongoDB Atlas Search.

    Args:
        collection: MongoDB collection containing candidate chunks.
        query_text: Normalised job description text (plain string, not embedded).
        top_k:      Max chunk hits to return (defaults to ``config.LEXICAL_TOP_K``).
        tenant_id:  When provided, restricts results to this tenant (SaaS mode).
        job_id:     When provided, restricts results to this job (SaaS mode).

    Returns:
        Ordered list of ChunkHit, best BM25 score first.

    Raises:
        RuntimeError: If the Atlas Search index does not exist.
    """
    k = top_k if top_k is not None else config.LEXICAL_TOP_K

    # Build the $search stage.
    # In SaaS mode we wrap the text query in a compound/must clause and add
    # equals filters for tenant_id and job_id so results are strictly scoped.
    if tenant_id or job_id:
        must_clauses = [{"text": {"query": query_text, "path": "text"}}]
        filter_clauses = []
        if tenant_id:
            filter_clauses.append({"equals": {"path": "tenant_id", "value": tenant_id}})
        if job_id:
            filter_clauses.append({"equals": {"path": "job_id", "value": job_id}})

        search_stage: dict = {
            "$search": {
                "index": config.TEXT_INDEX_NAME,
                "compound": {
                    "must": must_clauses,
                    "filter": filter_clauses,
                },
            }
        }
        logger.debug(
            "Lexical search scoped to tenant=%s  job=%s", tenant_id, job_id
        )
    else:
        # Legacy / single-tenant mode — no tenant filter applied.
        search_stage = {
            "$search": {
                "index": config.TEXT_INDEX_NAME,
                "text": {
                    "query": query_text,
                    "path": "text",
                },
            }
        }

    pipeline = [
        search_stage,
        {
            # Materialise the Atlas Search score for downstream logging/debug.
            "$addFields": {"_lex_score": {"$meta": "searchScore"}}
        },
        {"$limit": k},
        {
            "$project": {
                "_id": 0,
                "candidate_id": 1,
                "chunk_id": 1,
                "section": 1,
                "source_key": 1,
                "_lex_score": 1,
            }
        },
    ]

    try:
        results = list(collection.aggregate(pipeline))
    except Exception as exc:
        _msg = str(exc).lower()
        if "index not found" in _msg or "indexnotfound" in _msg or "no such index" in _msg:
            raise RuntimeError(
                f"Atlas Search index '{config.TEXT_INDEX_NAME}' not found on collection "
                f"'{collection.name}'. Create it in the Atlas UI — see phase2/README.md."
            ) from exc
        raise

    logger.info("Lexical search: %d chunk hits (top_k=%d)", len(results), k)
    return [
        ChunkHit(
            candidate_id=r["candidate_id"],
            chunk_id=r["chunk_id"],
            section=r.get("section", "unknown"),
            source_key=r.get("source_key", ""),
        )
        for r in results
    ]
