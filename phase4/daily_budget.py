"""
Phase 4 Persistent Daily Budget & Resumable Cache Tracker.
Pure JSON File-Based Persistence (Zero SQLite).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from phase4 import config

logger = logging.getLogger(__name__)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def compute_resume_hash(text: str) -> str:
    """Compute deterministic SHA256 hash of normalized resume text."""
    normalized = " ".join(text.split()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_cache_key(
    jd_id: str,
    resume_hash: str,
    rubric_version: str,
    tenant_id: Optional[str] = None,
    application_id: Optional[str] = None,
    resume_version: Optional[Union[int, str]] = None,
    jd_hash: Optional[str] = None,
) -> str:
    """
    Unique deterministic key identifying an evaluation task.
    In multi-tenant production, incorporates tenant_id, job_id, application_id,
    resume_version, resume_hash, jd_hash, and rubric_version to ensure complete
    isolation and prevent cross-tenant or cross-revision collisions.
    """
    if tenant_id or application_id or resume_version or jd_hash:
        seed = (
            f"{str(tenant_id or '').strip()}:"
            f"{str(jd_id).strip()}:"
            f"{str(application_id or '').strip()}:"
            f"{str(resume_version or '').strip()}:"
            f"{str(resume_hash).strip()}:"
            f"{str(jd_hash or '').strip()}:"
            f"{str(rubric_version).strip()}"
        )
    else:
        seed = f"{jd_id.strip()}:{resume_hash.strip()}:{rubric_version.strip()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def compute_production_cache_key(
    tenant_id: str,
    job_id: str,
    application_id: str,
    resume_version: Union[int, str],
    resume_hash: str,
    jd_hash: str,
    rubric_version: str,
) -> str:
    """Explicit multi-tenant production evaluation identity."""
    return compute_cache_key(
        jd_id=job_id,
        resume_hash=resume_hash,
        rubric_version=rubric_version,
        tenant_id=tenant_id,
        application_id=application_id,
        resume_version=resume_version,
        jd_hash=jd_hash,
    )


class DailyBudget:
    """
    Tracks daily token and request consumption against Groq free tier limits.
    Provides resumability via cached evaluations.
    Supports dual persistence:
      - Production: MongoDB Atlas (atomic find_one_and_update, shared across Lambda workers)
      - Local / CLI: Pure JSON File-Based Persistence (Zero SQLite).
    """

    def __init__(
        self,
        budget_file: Path = config.BUDGET_FILE,
        cache_dir: Path = config.CACHE_DIR,
        daily_token_limit: int = config.RATE_LIMIT_TPD,
        daily_request_limit: int = config.RATE_LIMIT_RPD,
        stop_threshold: float = config.DAILY_BUDGET_STOP_THRESHOLD,
        mongo_db: Optional[Any] = None,
    ) -> None:
        self.budget_file = Path(budget_file)
        self.cache_dir = Path(cache_dir)
        self.daily_token_limit = daily_token_limit
        self.daily_request_limit = daily_request_limit
        self.stop_threshold = stop_threshold
        self.mongo_db = mongo_db
        self._lock = Lock()

        # Ensure directory structure for file-based fallback
        if self.mongo_db is None:
            self.budget_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _read_budget_data(self) -> Dict[str, Dict[str, int]]:
        if not self.budget_file.exists():
            return {}
        try:
            with open(self.budget_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to parse budget file %s (%s). Starting fresh.", self.budget_file, exc)
            return {}

    def _write_budget_data(self, data: Dict[str, Dict[str, int]]) -> None:
        temp_file = self.budget_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(self.budget_file)

    def get_usage_today(self, date_str: Optional[str] = None) -> Dict[str, int]:
        """Returns usage stats for the specified day (default today UTC)."""
        date_key = date_str or _today_utc()
        if self.mongo_db is not None:
            doc = self.mongo_db["phase4_daily_budget"].find_one({"_id": date_key})
            if doc:
                return {
                    "request_count": doc.get("request_count", 0),
                    "prompt_tokens": doc.get("prompt_tokens", 0),
                    "completion_tokens": doc.get("completion_tokens", 0),
                    "total_tokens": doc.get("total_tokens", 0),
                }
            return {
                "request_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        with self._lock:
            data = self._read_budget_data()
            return data.get(date_key, {
                "request_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            })

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: Optional[int] = None,
        requests: int = 1,
        date_str: Optional[str] = None,
    ) -> Dict[str, int]:
        """Record token and request usage for today (atomic in MongoDB)."""
        date_key = date_str or _today_utc()
        tot = total_tokens if total_tokens is not None else (prompt_tokens + completion_tokens)

        if self.mongo_db is not None:
            from pymongo import ReturnDocument
            res = self.mongo_db["phase4_daily_budget"].find_one_and_update(
                {"_id": date_key},
                {
                    "$inc": {
                        "request_count": requests,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": tot,
                    },
                    "$set": {
                        "date": date_key,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            return {
                "request_count": res.get("request_count", 0),
                "prompt_tokens": res.get("prompt_tokens", 0),
                "completion_tokens": res.get("completion_tokens", 0),
                "total_tokens": res.get("total_tokens", 0),
            }

        with self._lock:
            data = self._read_budget_data()
            current = data.get(date_key, {
                "request_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            })

            current["request_count"] += requests
            current["prompt_tokens"] += prompt_tokens
            current["completion_tokens"] += completion_tokens
            current["total_tokens"] += tot

            data[date_key] = current
            self._write_budget_data(data)
            return current

    def is_budget_exceeded(self, threshold: Optional[float] = None) -> bool:
        """Check if today's usage exceeds the configured stop threshold (default 90%)."""
        thresh = threshold if threshold is not None else self.stop_threshold
        usage = self.get_usage_today()
        token_cap = int(self.daily_token_limit * thresh)
        req_cap = int(self.daily_request_limit * thresh)

        return (usage["total_tokens"] >= token_cap) or (usage["request_count"] >= req_cap)

    def get_budget_status(self) -> Dict[str, Any]:
        """Returns comprehensive status dictionary for dashboard/status endpoint."""
        usage = self.get_usage_today()
        token_used = usage["total_tokens"]
        req_used = usage["request_count"]

        token_remaining = max(0, self.daily_token_limit - token_used)
        req_remaining = max(0, self.daily_request_limit - req_used)
        pct_tokens = round((token_used / self.daily_token_limit) * 100, 2) if self.daily_token_limit else 0.0

        is_exceeded = self.is_budget_exceeded()
        stop_threshold_tokens = int(self.daily_token_limit * self.stop_threshold)

        return {
            "date": _today_utc(),
            "tokens_used_today": token_used,
            "tokens_remaining": token_remaining,
            "daily_token_limit": self.daily_token_limit,
            "tokens_used_pct": pct_tokens,
            "requests_used_today": req_used,
            "requests_remaining": req_remaining,
            "daily_request_limit": self.daily_request_limit,
            "stop_threshold_pct": round(self.stop_threshold * 100, 1),
            "stop_threshold_tokens": stop_threshold_tokens,
            "is_budget_exceeded": is_exceeded,
        }

    # ── Resumable Evaluation Cache ───────────────────────────────────────────

    def get_cached_evaluation(
        self,
        jd_id: str,
        resume_hash: str,
        rubric_version: str,
        tenant_id: Optional[str] = None,
        application_id: Optional[str] = None,
        resume_version: Optional[Union[int, str]] = None,
        jd_hash: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve previously completed evaluation if it exists."""
        key = compute_cache_key(
            jd_id=jd_id,
            resume_hash=resume_hash,
            rubric_version=rubric_version,
            tenant_id=tenant_id,
            application_id=application_id,
            resume_version=resume_version,
            jd_hash=jd_hash,
        )
        if self.mongo_db is not None:
            doc = self.mongo_db["phase4_evaluation_cache"].find_one({"_id": key}, {"_id": 0})
            return doc

        cache_path = self.cache_dir / f"{key}.json"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Failed to read cache file %s (%s).", cache_path, exc)
        return None

    def save_cached_evaluation(
        self,
        jd_id: str,
        resume_hash: str,
        rubric_version: str,
        resume_id: str,
        evaluation_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        application_id: Optional[str] = None,
        resume_version: Optional[Union[int, str]] = None,
        jd_hash: Optional[str] = None,
    ) -> str:
        """Save completed evaluation to cache for fast resumption."""
        key = compute_cache_key(
            jd_id=jd_id,
            resume_hash=resume_hash,
            rubric_version=rubric_version,
            tenant_id=tenant_id,
            application_id=application_id,
            resume_version=resume_version,
            jd_hash=jd_hash,
        )
        payload: Dict[str, Any] = {
            "cache_key": key,
            "jd_id": jd_id,
            "resume_id": resume_id,
            "resume_hash": resume_hash,
            "rubric_version": rubric_version,
            "evaluation": evaluation_data,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        if tenant_id:
            payload["tenant_id"] = tenant_id
        if application_id:
            payload["application_id"] = application_id
        if resume_version is not None:
            payload["resume_version"] = resume_version
        if jd_hash:
            payload["jd_hash"] = jd_hash

        if self.mongo_db is not None:
            mongo_doc = dict(payload)
            mongo_doc["_id"] = key
            self.mongo_db["phase4_evaluation_cache"].replace_one({"_id": key}, mongo_doc, upsert=True)
            return key

        cache_path = self.cache_dir / f"{key}.json"
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return key
