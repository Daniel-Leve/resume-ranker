"""
Phase 2 Voyage AI embedding client.

Wraps the ``voyageai`` Python SDK with:
- Configurable batching (default 72 texts per API call).
- Exponential backoff retry on transient errors (max 3 attempts).
- Strict input_type enforcement: "document" for chunks, "query" for JDs.
- No logging of resume text or personal information.

API key is read from the VOYAGE_API_KEY environment variable.
Never pass the key as a function argument or log it.
"""
from __future__ import annotations

import logging
import time
from typing import List, Literal

import voyageai

from phase2 import config

logger = logging.getLogger(__name__)

InputType = Literal["document", "query"]

# Valid input_type values accepted by this module
_VALID_INPUT_TYPES: frozenset[str] = frozenset({"document", "query"})


def _get_client() -> voyageai.Client:
    """Create a Voyage AI client from the configured API key."""
    if not config.VOYAGE_API_KEY:
        raise EnvironmentError(
            "VOYAGE_API_KEY is not set. "
            "Copy .env.example to .env and add your Voyage API key."
        )
    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


def embed_texts(
    texts: List[str],
    input_type: InputType,
    model: str | None = None,
    batch_size: int | None = None,
    max_retries: int = 3,
    base_delay_s: float = 2.0,
) -> List[List[float]]:
    """
    Embed a list of texts using Voyage AI.

    IMPORTANT:
        Use ``input_type="document"`` when embedding resume chunks (indexing).
        Use ``input_type="query"``    when embedding job descriptions (search).
        Mixing input types will degrade retrieval quality.

    Args:
        texts:         Texts to embed.  Must not be empty.
        input_type:    "document" or "query" — NEVER mix within a pipeline run.
        model:         Override model (defaults to ``config.VOYAGE_MODEL``).
        batch_size:    Texts per API call (defaults to ``config.VOYAGE_BATCH_SIZE``).
        max_retries:   Maximum retry attempts per batch on transient failure.
        base_delay_s:  Initial backoff delay in seconds (doubles each retry).

    Returns:
        List of 1024-float embedding vectors, one per input text, in input order.

    Raises:
        ValueError:       If ``input_type`` is invalid or ``texts`` is empty.
        EnvironmentError: If VOYAGE_API_KEY is not set.
        RuntimeError:     If all retry attempts for a batch are exhausted.
    """
    if not texts:
        return []

    if input_type not in _VALID_INPUT_TYPES:
        raise ValueError(
            f"Invalid input_type={input_type!r}. Must be 'document' or 'query'."
        )

    model = model or config.VOYAGE_MODEL
    batch_size = batch_size or config.VOYAGE_BATCH_SIZE
    client = _get_client()

    all_embeddings: List[List[float]] = []
    total_batches = (len(texts) + batch_size - 1) // batch_size

    logger.info(
        "Embedding %d text(s) in %d batch(es) | model=%s | input_type=%s",
        len(texts), total_batches, model, input_type,
    )

    for batch_num, start in enumerate(range(0, len(texts), batch_size), start=1):
        batch = texts[start : start + batch_size]

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                result = client.embed(batch, model=model, input_type=input_type)
                all_embeddings.extend(result.embeddings)
                logger.debug(
                    "Batch %d/%d OK (%d texts)",
                    batch_num, total_batches, len(batch),
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    delay = base_delay_s * (2 ** (attempt - 1))
                    logger.warning(
                        "Voyage API error — batch %d/%d attempt %d/%d: %s. "
                        "Retrying in %.1fs...",
                        batch_num, total_batches, attempt, max_retries, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Voyage API failed — batch %d/%d after %d attempts: %s",
                        batch_num, total_batches, max_retries, exc,
                    )
                    raise RuntimeError(
                        f"Voyage embedding failed after {max_retries} attempts "
                        f"(batch {batch_num}/{total_batches})"
                    ) from last_exc

    if len(all_embeddings) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: expected {len(texts)}, got {len(all_embeddings)}."
        )

    logger.info(
        "Embeddings complete: %d vectors | model=%s | input_type=%s",
        len(all_embeddings), model, input_type,
    )
    return all_embeddings
