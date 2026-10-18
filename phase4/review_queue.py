"""
Phase 4g: Human Review Queue Manager.
Manages flagged candidate evaluations and persists human override decisions as labeled examples.
Pure JSON File-Based Persistence (Zero SQLite).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Literal, Optional

from phase4 import config
from phase4.schemas import ReviewQueueItem

logger = logging.getLogger(__name__)


class ReviewQueueManager:
    """
    Thread-safe review queue manager.
    Supports dual persistence:
      - Production: MongoDB Atlas (collections phase4_review_queue and phase4_review_history)
      - Local / CLI: JSON files (Zero SQLite).
    """

    def __init__(
        self,
        queue_file: Path = config.REVIEW_QUEUE_FILE,
        history_file: Path = config.REVIEW_HISTORY_FILE,
        mongo_db: Optional[Any] = None,
    ) -> None:
        self.queue_file = Path(queue_file)
        self.history_file = Path(history_file)
        self.mongo_db = mongo_db
        self._lock = Lock()

        if self.mongo_db is None:
            try:
                self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("Could not create review queue directory: %s", exc)

    def _load_json(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Error reading JSON file %s: %s", path, exc)
            return []

    def _save_json(self, path: Path, data: List[Dict[str, Any]]) -> None:
        try:
            temp_file = path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(path)
        except OSError as exc:
            logger.warning("Could not save review queue file %s: %s", path, exc)

    def enqueue(
        self,
        resume_id: str,
        candidate_id: str,
        job_id: str,
        flag_reasons: List[str],
        rerank_rank: Optional[int] = None,
        weighted_score: float = 0.0,
        payload: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> ReviewQueueItem:
        """Add a flagged candidate evaluation to the human review queue."""
        item = ReviewQueueItem(
            resume_id=resume_id,
            candidate_id=candidate_id,
            job_id=job_id,
            tenant_id=tenant_id,
            status="NEEDS_REVIEW",
            flag_reasons=flag_reasons,
            rerank_rank=rerank_rank,
            weighted_score=weighted_score,
            payload=payload or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        if self.mongo_db is not None:
            doc = item.model_dump()
            doc["_id"] = f"{tenant_id or 'default'}:{job_id}:{resume_id}"
            self.mongo_db["phase4_review_queue"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            logger.info("Enqueued candidate %s into MongoDB review queue (flags: %s)", candidate_id, flag_reasons)
            return item

        with self._lock:
            items = self._load_json(self.queue_file)
            # Check if item already exists in queue; update if so
            existing_idx = next((i for i, x in enumerate(items) if x.get("resume_id") == resume_id), None)
            if existing_idx is not None:
                items[existing_idx] = item.model_dump()
            else:
                items.append(item.model_dump())
            self._save_json(self.queue_file, items)

        logger.info("Enqueued candidate %s into review queue (flags: %s)", candidate_id, flag_reasons)
        return item

    def list_items(
        self,
        job_id: Optional[str] = None,
        status: Optional[str] = "NEEDS_REVIEW",
        tenant_id: Optional[str] = None,
    ) -> List[ReviewQueueItem]:
        """List review queue items filtered by job_id, status, or tenant_id."""
        if self.mongo_db is not None:
            filter_q: Dict[str, Any] = {}
            if job_id:
                filter_q["job_id"] = job_id
            if status:
                filter_q["status"] = status
            if tenant_id:
                filter_q["tenant_id"] = tenant_id
            docs = list(self.mongo_db["phase4_review_queue"].find(filter_q, {"_id": 0}))
            return [ReviewQueueItem.model_validate(d) for d in docs]

        with self._lock:
            items_raw = self._load_json(self.queue_file)
            res = []
            for raw in items_raw:
                if job_id and raw.get("job_id") != job_id:
                    continue
                if status and raw.get("status") != status:
                    continue
                if tenant_id and raw.get("tenant_id") and raw.get("tenant_id") != tenant_id:
                    continue
                res.append(ReviewQueueItem.model_validate(raw))
            return res

    def get_item(
        self,
        resume_id: str,
        job_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[ReviewQueueItem]:
        """Retrieve single item by resume_id or candidate_id."""
        if self.mongo_db is not None:
            query: Dict[str, Any] = {
                "$or": [{"resume_id": resume_id}, {"candidate_id": resume_id}]
            }
            if job_id:
                query["job_id"] = job_id
            if tenant_id:
                query["tenant_id"] = tenant_id
            doc = self.mongo_db["phase4_review_queue"].find_one(query, {"_id": 0})
            return ReviewQueueItem.model_validate(doc) if doc else None

        with self._lock:
            items = self._load_json(self.queue_file)
            for raw in items:
                if raw.get("resume_id") == resume_id or raw.get("candidate_id") == resume_id:
                    if job_id and raw.get("job_id") != job_id:
                        continue
                    if tenant_id and raw.get("tenant_id") and raw.get("tenant_id") != tenant_id:
                        continue
                    return ReviewQueueItem.model_validate(raw)
            return None

    def resolve(
        self,
        resume_id: str,
        action: Literal["promote", "confirm_reject", "fix_rubric"],
        notes: Optional[str] = None,
        resolved_by: str = "recruiter",
        job_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> ReviewQueueItem:
        """
        Resolve a review queue item and archive it into history as a labeled training/audit example.
        """
        status_map = {
            "promote": "PROMOTED",
            "confirm_reject": "CONFIRMED_REJECT",
            "fix_rubric": "RUBRIC_FIX",
        }
        if action not in status_map:
            raise ValueError(f"Invalid resolution action: {action}. Must be one of {list(status_map.keys())}")

        now_iso = datetime.now(timezone.utc).isoformat()
        override_notes = notes or f"Action taken: {action}"

        if self.mongo_db is not None:
            query: Dict[str, Any] = {
                "$or": [{"resume_id": resume_id}, {"candidate_id": resume_id}]
            }
            if job_id:
                query["job_id"] = job_id
            if tenant_id:
                query["tenant_id"] = tenant_id

            doc = self.mongo_db["phase4_review_queue"].find_one(query)
            if not doc:
                raise KeyError(f"Item with resume_id {resume_id} not found in review queue.")

            doc["status"] = status_map[action]
            doc["resolved_at"] = now_iso
            doc["resolved_by"] = resolved_by
            doc["override_notes"] = override_notes

            self.mongo_db["phase4_review_queue"].update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "status": status_map[action],
                    "resolved_at": now_iso,
                    "resolved_by": resolved_by,
                    "override_notes": override_notes,
                }}
            )
            # Insert into history collection
            history_doc = dict(doc)
            history_doc["_id"] = f"{doc['_id']}:{now_iso}"
            self.mongo_db["phase4_review_history"].insert_one(history_doc)

            clean_doc = {k: v for k, v in doc.items() if k != "_id"}
            resolved_item = ReviewQueueItem.model_validate(clean_doc)
            logger.info("Resolved review item %s with action '%s' by %s in MongoDB.", resume_id, action, resolved_by)
            return resolved_item

        with self._lock:
            items = self._load_json(self.queue_file)
            item_idx = next(
                (i for i, x in enumerate(items) if x.get("resume_id") == resume_id or x.get("candidate_id") == resume_id),
                None
            )
            if item_idx is None:
                raise KeyError(f"Item with resume_id {resume_id} not found in review queue.")

            raw_item = items.pop(item_idx)
            raw_item["status"] = status_map[action]
            raw_item["resolved_at"] = now_iso
            raw_item["resolved_by"] = resolved_by
            raw_item["override_notes"] = override_notes

            resolved_item = ReviewQueueItem.model_validate(raw_item)

            # Save updated active queue
            self._save_json(self.queue_file, items)

            # Append to history / labeled examples file
            history = self._load_json(self.history_file)
            history.append(resolved_item.model_dump())
            self._save_json(self.history_file, history)

        logger.info(
            "Resolved review item for %s with action '%s' by %s.",
            resume_id, action, resolved_by
        )
        return resolved_item


GLOBAL_REVIEW_QUEUE = ReviewQueueManager()
