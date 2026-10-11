"""
Secrets Manager helper — Block 3.

Centralised retrieval of sensitive credentials from AWS Secrets Manager.
Secrets are cached in-process for the lifetime of the Lambda execution
environment (warm start) to avoid rate limits and reduce latency.

Environment variables used:
  MONGODB_URI_SECRET_ARN   — ARN of the secret holding the MongoDB URI string
  VOYAGE_API_KEY_SECRET_ARN — ARN of the secret holding the Voyage API key

The secret value stored in Secrets Manager is a plain string (not JSON)
for simplicity. If you later need to store multiple values in one secret
(e.g., {uri, options}), wrap with json.loads() in get_secret_string().

Fall-through behaviour:
  If the _SECRET_ARN env var is not set, the code falls back to reading
  MONGODB_URI / VOYAGE_API_KEY directly from environment. This preserves
  local development and pytest compatibility where Secrets Manager is
  not available.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# In-process cache: {secret_arn: secret_string}
_secret_cache: dict[str, str] = {}


def get_secret_string(secret_arn: str) -> str:
    """
    Retrieve a plaintext secret from Secrets Manager, with in-process caching.

    Args:
        secret_arn: The full ARN of the secret.

    Returns:
        The secret value as a string.

    Raises:
        RuntimeError: If the secret cannot be retrieved.
    """
    if secret_arn in _secret_cache:
        return _secret_cache[secret_arn]

    try:
        import boto3
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        value = response.get("SecretString", "")
        if not value:
            raise RuntimeError(f"Secret {secret_arn} has an empty SecretString.")
        _secret_cache[secret_arn] = value
        logger.info("Loaded secret from Secrets Manager (arn suffix: ...%s)", secret_arn[-12:])
        return value
    except Exception as exc:
        raise RuntimeError(f"Failed to retrieve secret {secret_arn}: {exc}") from exc


def get_mongodb_uri() -> str:
    """
    Return the MongoDB URI, preferring Secrets Manager over env var.

    Order of precedence:
      1. MONGODB_URI_SECRET_ARN → Secrets Manager (production)
      2. MONGODB_URI env var directly (local dev / legacy)
    """
    arn = os.environ.get("MONGODB_URI_SECRET_ARN", "").strip()
    if arn:
        return get_secret_string(arn)
    # Fall-through for local development
    uri = os.environ.get("MONGODB_URI", "")
    if not uri:
        raise RuntimeError(
            "Neither MONGODB_URI_SECRET_ARN nor MONGODB_URI is set. "
            "Set MONGODB_URI for local development."
        )
    return uri


def get_voyage_api_key() -> str:
    """
    Return the Voyage AI API key, preferring Secrets Manager over env var.

    Order of precedence:
      1. VOYAGE_API_KEY_SECRET_ARN → Secrets Manager (production)
      2. VOYAGE_API_KEY env var directly (local dev / legacy)
    """
    arn = os.environ.get("VOYAGE_API_KEY_SECRET_ARN", "").strip()
    if arn:
        return get_secret_string(arn)
    key = os.environ.get("VOYAGE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Neither VOYAGE_API_KEY_SECRET_ARN nor VOYAGE_API_KEY is set. "
            "Set VOYAGE_API_KEY for local development."
        )
    return key


def clear_cache_for_testing() -> None:
    """
    Clear the in-process secret cache.
    Only intended for use in unit tests that need to reset state.
    """
    _secret_cache.clear()
