"""
Document Builder for Phase 3 Reranking.

Reconstructs a coherent candidate profile from the individual chunks stored
in MongoDB during Phase 2.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from pymongo.collection import Collection

from phase3 import config

logger = logging.getLogger(__name__)


@dataclass
class ReconstructedDocument:
    candidate_id: str
    text: str
    chunk_ids: List[str]
    truncated: bool


def build_candidate_document(
    collection: Collection,
    candidate_id: str,
    max_chars: int | None = None,
) -> ReconstructedDocument:
    """
    Retrieve all chunks for a candidate from MongoDB, sort them by chunk_index,
    and reconstruct a single coherent text document for the reranker.

    Args:
        collection:   MongoDB candidate_chunks collection.
        candidate_id: The ID of the candidate to rebuild.
        max_chars:    Maximum string length. Defaults to config.RERANK_MAX_DOCUMENT_CHARS.

    Returns:
        ReconstructedDocument containing the text and metadata.
    """
    max_chars = max_chars or config.RERANK_MAX_DOCUMENT_CHARS

    # Fetch chunks from MongoDB
    cursor = collection.find(
        {"candidate_id": candidate_id},
        {"chunk_id": 1, "section": 1, "text": 1, "chunk_index": 1, "_id": 0}
    ).sort("chunk_index", 1)
    
    chunks = list(cursor)
    
    if not chunks:
        logger.warning("No chunks found in MongoDB for candidate %s", candidate_id)
        return ReconstructedDocument(
            candidate_id=candidate_id,
            text="",
            chunk_ids=[],
            truncated=False,
        )

    # Reconstruct document
    # Format: 
    # [SECTION]
    # text...
    
    doc_parts = []
    chunk_ids = []
    current_chars = 0
    truncated = False

    # Title block
    header = f"[CANDIDATE PROFILE]\nCandidate ID: {candidate_id}\n\n"
    doc_parts.append(header)
    current_chars += len(header)

    for chunk in chunks:
        section_label = str(chunk.get("section", "unknown")).upper()
        chunk_text = chunk.get("text", "").strip()
        
        if not chunk_text:
            continue

        # Format the block
        block = f"[{section_label}]\n{chunk_text}\n\n"
        
        if current_chars + len(block) > max_chars:
            # We must truncate
            allowed_len = max_chars - current_chars
            if allowed_len > 20: # arbitrary minimum to bother adding text
                doc_parts.append(block[:allowed_len] + "\n...[TRUNCATED]")
                chunk_ids.append(chunk["chunk_id"])
            truncated = True
            logger.warning(
                "Candidate %s document exceeded max_chars (%d). Truncated.",
                candidate_id, max_chars
            )
            break
            
        doc_parts.append(block)
        chunk_ids.append(chunk["chunk_id"])
        current_chars += len(block)

    full_text = "".join(doc_parts).strip()
    
    return ReconstructedDocument(
        candidate_id=candidate_id,
        text=full_text,
        chunk_ids=chunk_ids,
        truncated=truncated,
    )
