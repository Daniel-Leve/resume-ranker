"""
Database schema indexes initialization and verification for Block 5.

Ensures necessary operational indexes exist on:
- tenants
- tenant_memberships
- jobs
- applications
- screening_runs
- candidate_chunks
"""
from __future__ import annotations

import logging
from pymongo.database import Database

logger = logging.getLogger(__name__)


def ensure_domain_indexes(db: Database) -> dict[str, list[str]]:
    """
    Create all required domain indexes across SaaS collections.
    Returns a dictionary of collection_name -> list of index names created/ensured.
    """
    created = {}

    # 1. tenants
    db["tenants"].create_index([("tenant_id", 1)], unique=True, name="idx_tenant_id_unique")
    created["tenants"] = ["idx_tenant_id_unique"]

    # 2. tenant_memberships
    db["tenant_memberships"].create_index(
        [("user_sub", 1), ("tenant_id", 1)],
        unique=True,
        name="idx_user_tenant_unique"
    )
    db["tenant_memberships"].create_index(
        [("tenant_id", 1)],
        name="idx_membership_tenant_lookup"
    )
    created["tenant_memberships"] = ["idx_user_tenant_unique", "idx_membership_tenant_lookup"]

    # 3. jobs
    db["jobs"].create_index(
        [("tenant_id", 1), ("status", 1)],
        name="idx_jobs_tenant_status"
    )
    db["jobs"].create_index(
        [("job_id", 1)],
        name="idx_jobs_job_id"
    )
    created["jobs"] = ["idx_jobs_tenant_status", "idx_jobs_job_id"]

    # 4. applications
    db["applications"].create_index(
        [("tenant_id", 1), ("job_id", 1), ("phase2_status", 1)],
        name="idx_apps_tenant_job_phase2_status"
    )
    db["applications"].create_index(
        [("tenant_id", 1), ("candidate_id", 1)],
        name="idx_apps_tenant_candidate"
    )
    db["applications"].create_index(
        [("application_id", 1)],
        name="idx_apps_application_id"
    )
    created["applications"] = [
        "idx_apps_tenant_job_phase2_status",
        "idx_apps_tenant_candidate",
        "idx_apps_application_id",
    ]

    # 5. screening_runs
    db["screening_runs"].create_index(
        [("tenant_id", 1), ("job_id", 1), ("status", 1)],
        name="idx_screening_runs_tenant_job_status"
    )
    db["screening_runs"].create_index(
        [("screening_run_id", 1)],
        name="idx_screening_runs_run_id"
    )
    created["screening_runs"] = [
        "idx_screening_runs_tenant_job_status",
        "idx_screening_runs_run_id",
    ]

    # 6. candidate_chunks
    db["candidate_chunks"].create_index(
        [("source_key", 1), ("content_hash", 1)],
        name="idx_source_key_hash"
    )
    db["candidate_chunks"].create_index(
        [("tenant_id", 1), ("job_id", 1), ("candidate_id", 1)],
        name="idx_tenant_job_candidate"
    )
    db["candidate_chunks"].create_index(
        [("tenant_id", 1), ("job_id", 1), ("application_id", 1)],
        name="idx_tenant_job_application"
    )
    created["candidate_chunks"] = [
        "idx_source_key_hash",
        "idx_tenant_job_candidate",
        "idx_tenant_job_application",
    ]

    logger.info("Domain indexes ensured successfully across all collections.")
    return created
