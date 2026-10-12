"""
Centralized MongoDB connection management with connection pooling across Lambda invocations.

Supports warm start connection reuse across AWS Lambda handler calls while
maintaining full backward-compatibility with existing tests and local scripts.
"""
from __future__ import annotations

import logging
from typing import Optional

import certifi
from pymongo import MongoClient

from api.auth.secrets import get_mongodb_uri

logger = logging.getLogger(__name__)

# Global client cache per Lambda execution environment
_CLIENT_CACHE: dict[str, MongoClient] = {}


def get_mongo_client(
    uri: Optional[str] = None,
    max_pool_size: int = 50,
    min_pool_size: int = 5,
    max_idle_time_ms: int = 45_000,
    server_selection_timeout_ms: int = 10_000,
    connect_timeout_ms: int = 10_000,
    socket_timeout_ms: int = 45_000,
) -> MongoClient:
    """
    Get or create a cached MongoClient instance for warm-start reuse.

    If a client already exists and is healthy, it is reused.
    If no client exists or ping fails, a new MongoClient is initialized.
    """
    connection_uri = (uri or get_mongodb_uri()).strip()
    client = _CLIENT_CACHE.get(connection_uri)

    if client is not None:
        try:
            # Fast ping check to verify socket health
            client.admin.command("ping")
            return client
        except Exception as exc:
            logger.warning("Cached MongoClient ping failed (%s), reconnecting...", exc)
            try:
                client.close()
            except Exception:
                pass
            _CLIENT_CACHE.pop(connection_uri, None)

    logger.info("Initializing new MongoClient with connection pool (max=%d, min=%d)", max_pool_size, min_pool_size)
    new_client = MongoClient(
        connection_uri,
        maxPoolSize=max_pool_size,
        minPoolSize=min_pool_size,
        maxIdleTimeMS=max_idle_time_ms,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        connectTimeoutMS=connect_timeout_ms,
        socketTimeoutMS=socket_timeout_ms,
        tlsCAFile=certifi.where(),
        retryWrites=True,
    )
    _CLIENT_CACHE[connection_uri] = new_client
    return new_client


def close_mongo_client(uri: Optional[str] = None) -> None:
    """Close and clear cached clients (primarily for testing and cleanup)."""
    if uri:
        client = _CLIENT_CACHE.pop(uri.strip(), None)
        if client:
            try:
                client.close()
            except Exception:
                pass
    else:
        for client in list(_CLIENT_CACHE.values()):
            try:
                client.close()
            except Exception:
                pass
        _CLIENT_CACHE.clear()
