"""
Repeatable, idempotent migration utility for legacy database records (Block 5).

Supports dry-run reporting mode and safe execution without duplicating or corrupting records.

What it migrates:
1. Applications collection:
   - Sets candidate_id derived from candidate_name or _id if missing.
   - Initializes current_resume_version = 1 if missing.
   - Populates resume_versions array from s3_resume_key if missing.
   - Initializes updated_at timestamp if missing.
2. Screening runs collection:
   - Normalizes input_application_ids if missing (from candidate source keys or matching jobs).
3. Candidate chunks collection:
   - Sets resume_version = 1 on existing chunks where missing.
"""
from __future__ import annotations

import argparse
import logging
import re
from typing import Any, Dict
from pymongo.database import Database

logger = logging.getLogger(__name__)


def migrate_domain_models(db: Database, dry_run: bool = True) -> Dict[str, Any]:
    """
    Scan collections for legacy documents and migrate them to the normalized schema.

    Args:
        db: MongoDB Database instance
        dry_run: If True, reports documents to be modified without performing writes.

    Returns:
        Summary dict of inspect count and modified count per collection.
    """
    report = {
        "dry_run": dry_run,
        "applications": {"inspected": 0, "needs_migration": 0, "migrated": 0},
        "screening_runs": {"inspected": 0, "needs_migration": 0, "migrated": 0},
        "candidate_chunks": {"inspected": 0, "needs_migration": 0, "migrated": 0},
    }

    # 1. Applications Migration
    apps_col = db["applications"]
    for app in apps_col.find():
        report["applications"]["inspected"] += 1
        updates = {}

        if not app.get("candidate_id"):
            name = app.get("candidate_name", "")
            slug = re.sub(r"[^a-zA-Z0-9\-_]+", "-", name.lower()).strip("-")
            updates["candidate_id"] = slug or str(app["_id"])

        if "current_resume_version" not in app:
            updates["current_resume_version"] = 1

        if not app.get("resume_versions"):
            updates["resume_versions"] = [{
                "version": 1,
                "s3_resume_key": app.get("s3_resume_key", ""),
                "uploaded_at": app.get("created_at", ""),
                "status": app.get("phase2_status", "INDEXED"),
            }]

        if not app.get("updated_at"):
            updates["updated_at"] = app.get("created_at", "")

        if updates:
            report["applications"]["needs_migration"] += 1
            if not dry_run:
                apps_col.update_one({"_id": app["_id"]}, {"$set": updates})
                report["applications"]["migrated"] += 1

    # 2. Screening Runs Migration
    runs_col = db["screening_runs"]
    for run in runs_col.find():
        report["screening_runs"]["inspected"] += 1
        updates = {}

        if "input_application_ids" not in run:
            # Fallback to finding applications matching this job and tenant
            matching_apps = list(apps_col.find(
                {"job_id": run.get("job_id"), "tenant_id": run.get("tenant_id")},
                {"_id": 1}
            ))
            updates["input_application_ids"] = [str(a["_id"]) for a in matching_apps]

        if updates:
            report["screening_runs"]["needs_migration"] += 1
            if not dry_run:
                runs_col.update_one({"_id": run["_id"]}, {"$set": updates})
                report["screening_runs"]["migrated"] += 1

    # 3. Candidate Chunks Migration
    chunks_col = db["candidate_chunks"]
    legacy_chunks_count = chunks_col.count_documents({"resume_version": {"$exists": False}})
    report["candidate_chunks"]["inspected"] = chunks_col.count_documents({})
    report["candidate_chunks"]["needs_migration"] = legacy_chunks_count

    if legacy_chunks_count > 0 and not dry_run:
        result = chunks_col.update_many(
            {"resume_version": {"$exists": False}},
            {"$set": {"resume_version": 1}}
        )
        report["candidate_chunks"]["migrated"] = result.modified_count

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy MongoDB records to Block 5 schema.")
    parser.add_argument("--execute", action="store_true", help="Execute writes (defaults to dry-run).")
    args = parser.parse_args()

    from api.storage.mongo import get_mongo_client
    client = get_mongo_client()
    db = client["resume_screening"]
    res = migrate_domain_models(db, dry_run=not args.execute)
    print(res)
