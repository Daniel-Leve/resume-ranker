"""
API Handler — Manages Tenants, Jobs, Applications, and Screening triggers.

Block 3: Authentication & Tenant Isolation enforced on all protected routes.

Endpoints handled:
    POST   /tenants                             → requires auth (creates tenant + membership)
    POST   /tenants/{tenant_id}/jobs            → requires auth + ADMIN role in tenant
    GET    /tenants/{tenant_id}/jobs            → requires auth + MEMBER role in tenant
    GET    /tenants/{tenant_id}/jobs/{job_id}   → requires auth + MEMBER role in tenant
    POST   /jobs/{job_id}/applications          → PUBLIC (candidates upload resumes, no account needed)
    POST   /jobs/{job_id}/screening             → requires auth + ADMIN role in owning tenant
    GET    /jobs/{job_id}/screening-results     → requires auth + MEMBER role in owning tenant

Authentication model:
    - API Gateway is configured with a Cognito JWT Authorizer on protected routes.
    - The JWT is verified by API Gateway BEFORE the Lambda is invoked.
    - The Lambda reads the pre-verified claims from:
          event['requestContext']['authorizer']['claims']
    - Tenant membership is stored in MongoDB `tenant_memberships` collection:
          { user_sub, tenant_id, role: "ADMIN"|"MEMBER", created_at }
    - tenant_id from path parameters is NEVER trusted for authorization decisions.
      It is only used as a database lookup key after the auth check passes.

Security:
    - Presigned URLs are scoped to the exact S3 prefix for the tenant/job/application.
    - Secrets (MONGODB_URI, VOYAGE_API_KEY) are environment variables from Secrets Manager.
    - Resume PII (names, emails) is never logged — only IDs and counts.
    - Cross-tenant access is blocked at the membership lookup layer.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
import certifi
from pymongo import MongoClient

from api.auth.context import (
    AuthContext,
    extract_auth_context,
    get_user_tenant_membership,
    require_tenant_access,
)
from api.auth.secrets import get_mongodb_uri
from api.storage.mongo import get_mongo_client
from phase2.storage.s3_paths import build_saas_incoming_key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─── Environment ───────────────────────────────────────────────────────────────
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "resume_screening")
PRESIGNED_URL_EXPIRY_SECONDS = 900  # 15 minutes


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _response(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _get_mongo() -> MongoClient:
    return get_mongo_client(get_mongodb_uri())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _require_auth(event: dict) -> tuple[Optional[AuthContext], Optional[dict]]:
    """
    Extract and validate the authenticated user from the event.

    Returns:
        (AuthContext, None)         — when authenticated
        (None, error_response_dict) — when not authenticated (caller should return the dict)
    """
    auth = extract_auth_context(event)
    if not auth:
        return None, _response(401, {"error": "Authentication required."})
    return auth, None


def _resolve_job_tenant(db, job_id: str) -> Optional[str]:
    """
    Look up the tenant_id for a job from MongoDB.
    Returns None if the job does not exist.
    Never trusts a caller-supplied tenant_id.
    """
    job = db["jobs"].find_one({"_id": job_id}, {"tenant_id": 1})
    if not job:
        return None
    return job.get("tenant_id")


# ─── Route Handlers ────────────────────────────────────────────────────────────

def _post_tenant(event: dict) -> dict:
    """
    POST /tenants  [PROTECTED — requires valid JWT]
    Creates a new tenant (company) record in MongoDB AND creates an ADMIN
    membership record linking the authenticated user to this tenant.

    The authenticated user becomes the first ADMIN of the new tenant.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    body = json.loads(event.get("body") or "{}")
    name = body.get("name", "").strip()
    if not name:
        return _response(400, {"error": "Field 'name' is required."})

    tenant_id = _new_id()
    now = _now_iso()

    tenant_doc = {
        "_id": tenant_id,
        "tenant_id": tenant_id,
        "name": name,
        "created_at": now,
        "status": "ACTIVE",
        "created_by_sub": auth.user_sub,
    }
    membership_doc = {
        "_id": f"{auth.user_sub}:{tenant_id}",
        "user_sub": auth.user_sub,
        "tenant_id": tenant_id,
        "role": "ADMIN",
        "created_at": now,
    }

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        db["tenants"].insert_one(tenant_doc)
        db["tenant_memberships"].insert_one(membership_doc)

    logger.info("Created tenant %s by user_sub=%s", tenant_id, auth.user_sub)
    return _response(201, {"tenant_id": tenant_id, "name": name, "role": "ADMIN"})


def _post_job(event: dict) -> dict:
    """
    POST /tenants/{tenant_id}/jobs  [PROTECTED — requires ADMIN role in tenant]
    Creates a new job posting under the authenticated user's tenant.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    tenant_id_from_path = (event.get("pathParameters") or {}).get("tenant_id")
    if not tenant_id_from_path:
        return _response(400, {"error": "tenant_id path parameter missing."})

    body = json.loads(event.get("body") or "{}")
    title = body.get("title", "").strip()
    description = body.get("description", "").strip()
    if not title:
        return _response(400, {"error": "Field 'title' is required."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]

        # Authorization: verify caller is ADMIN of this specific tenant
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id_from_path, minimum_role="ADMIN"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have admin access to this tenant.",
                "code": "FORBIDDEN",
            })

        job_id = _new_id()
        doc = {
            "_id": job_id,
            "job_id": job_id,
            "tenant_id": tenant_id_from_path,
            "title": title,
            "description": description,
            "status": "OPEN",
            "created_at": _now_iso(),
            "application_count": 0,
        }
        db["jobs"].insert_one(doc)

    logger.info("Created job %s (tenant: %s)", job_id, tenant_id_from_path)
    return _response(201, {
        "job_id": job_id,
        "tenant_id": tenant_id_from_path,
        "title": title,
        "status": "OPEN",
    })


def _get_jobs(event: dict) -> dict:
    """
    GET /tenants/{tenant_id}/jobs  [PROTECTED — requires MEMBER role in tenant]
    Returns a list of all jobs for the tenant.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    tenant_id_from_path = (event.get("pathParameters") or {}).get("tenant_id")
    if not tenant_id_from_path:
        return _response(400, {"error": "tenant_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]

        # Authorization: verify caller is at least MEMBER of this tenant
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id_from_path, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this tenant.",
                "code": "FORBIDDEN",
            })

        # Tenant existence check
        tenant = db["tenants"].find_one({"_id": tenant_id_from_path})
        if not tenant:
            return _response(404, {"error": "Tenant not found."})

        jobs = list(db["jobs"].find({"tenant_id": tenant_id_from_path}, {"_id": 0}))

    return _response(200, {"jobs": jobs})


def _get_job(event: dict) -> dict:
    """
    GET /tenants/{tenant_id}/jobs/{job_id}  [PROTECTED — requires MEMBER role]
    Returns job details and current screening status.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    params = event.get("pathParameters") or {}
    tenant_id_from_path = params.get("tenant_id")
    job_id = params.get("job_id")

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]

        # Authorization: verify caller is MEMBER of this tenant
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id_from_path, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this tenant.",
                "code": "FORBIDDEN",
            })

        job = db["jobs"].find_one(
            {"_id": job_id, "tenant_id": tenant_id_from_path},
            {"_id": 0},
        )

    if not job:
        return _response(404, {"error": "Job not found."})
    return _response(200, job)


def _post_application(event: dict) -> dict:
    """
    POST /jobs/{job_id}/applications  [PUBLIC — no authentication required]

    Creates a new application and returns a secure presigned S3 URL so the
    candidate can upload their PDF directly to S3.

    This endpoint is intentionally public because job candidates do NOT have
    HR accounts — they are external users submitting their CV.

    Security controls applied instead:
      - The S3 key is derived server-side from the job's authoritative tenant_id
        (never from caller input).
      - The presigned URL is scoped to the exact S3 key and expires in 15 min.
      - The S3 key encodes tenant/job/application IDs, so uploads cannot
        escape the correct tenant prefix.
    """
    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    body = json.loads(event.get("body") or "{}")
    candidate_name = body.get("candidate_name", "").strip()
    if not candidate_name:
        return _response(400, {"error": "Field 'candidate_name' is required."})

    # Look up the tenant_id from MongoDB — never from the request
    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id}, {"tenant_id": 1, "status": 1})

    if not job:
        return _response(404, {"error": "Job not found."})

    if job.get("status") != "OPEN":
        return _response(409, {
            "error": "This job is not accepting applications.",
            "code": "JOB_CLOSED",
        })

    tenant_id = job["tenant_id"]
    application_id = _new_id()

    # Build the S3 key server-side from authoritative data only
    s3_key = build_saas_incoming_key(tenant_id, job_id, application_id)

    # Generate a presigned URL — the candidate uploads directly to S3
    s3 = boto3.client("s3")
    presigned_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": s3_key,
            "ContentType": "application/pdf",
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    # Derive stable candidate_id from candidate_name (lowercased slug) or application
    raw_name_slug = re.sub(r"[^a-zA-Z0-9\-_]+", "-", candidate_name.lower()).strip("-")
    candidate_id = raw_name_slug or application_id
    now = _now_iso()

    # Record application in MongoDB with full domain relationships and versioning
    initial_version = {
        "version": 1,
        "s3_resume_key": s3_key,
        "uploaded_at": now,
        "status": "PENDING_UPLOAD",
    }

    app_doc = {
        "_id": application_id,
        "application_id": application_id,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,   # stored for HR display
        "s3_resume_key": s3_key,
        "current_resume_version": 1,
        "resume_versions": [initial_version],
        "status": "PENDING_UPLOAD",
        "phase1_status": "NOT_STARTED",
        "phase2_status": "NOT_STARTED",
        "phase3_status": "NOT_STARTED",
        "created_at": now,
        "updated_at": now,
    }

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        db["applications"].insert_one(app_doc)
        db["jobs"].update_one(
            {"_id": job_id},
            {"$inc": {"application_count": 1}},
        )

    logger.info("Created application %s (job: %s)", application_id, job_id)
    return _response(201, {
        "application_id": application_id,
        "upload_url": presigned_url,
        "upload_expires_in_seconds": PRESIGNED_URL_EXPIRY_SECONDS,
        "s3_key": s3_key,
        "instructions": "PUT your PDF to the upload_url with Content-Type: application/pdf",
    })


def _post_screening(event: dict) -> dict:
    """
    POST /jobs/{job_id}/screening  [PROTECTED — requires ADMIN role in owning tenant]
    Triggers the Phase 2+3 Screening pipeline for all INDEXED applications.
    Pushes a message to the ScreeningQueue; processing is asynchronous.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]

        # Resolve job → trusted tenant_id (never from caller)
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        # Authorization: verify caller is ADMIN of the job's owning tenant
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="ADMIN"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have admin access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        # Guard against duplicate / concurrent active runs
        active_run = db["screening_runs"].find_one({
            "job_id": job_id,
            "tenant_id": tenant_id,
            "status": {"$in": ["QUEUED", "RUNNING", "RUNNING_PHASE2", "RUNNING_PHASE3"]},
        })
        if active_run:
            return _response(409, {
                "error": "A screening run is already in progress for this job.",
                "code": "SCREENING_ALREADY_IN_PROGRESS",
                "screening_run_id": active_run["screening_run_id"],
                "status": active_run["status"],
            })

        # Guard against premature screening: check for indexed applications
        indexed_count = db["applications"].count_documents({
            "job_id": job_id,
            "tenant_id": tenant_id,
            "phase2_status": "INDEXED",
        })
        if indexed_count == 0:
            total_count = db["applications"].count_documents({
                "job_id": job_id,
                "tenant_id": tenant_id,
            })
            if total_count == 0:
                return _response(409, {
                    "error": "No applications found for this job. Cannot trigger screening.",
                    "code": "NO_APPLICATIONS",
                    "eligible_candidate_count": 0,
                    "total_application_count": 0,
                })
            return _response(409, {
                "error": (
                    f"No applications are indexed for screening yet "
                    f"({total_count} application(s) pending processing)."
                ),
                "code": "APPLICATIONS_NOT_INDEXED",
                "eligible_candidate_count": 0,
                "total_application_count": total_count,
            })

        # Fetch the exact list of application IDs eligible for this screening run
        eligible_apps = list(db["applications"].find(
            {"job_id": job_id, "tenant_id": tenant_id, "phase2_status": "INDEXED"},
            {"_id": 1}
        )) if hasattr(db["applications"], "find") else []
        input_application_ids = [str(app["_id"]) for app in eligible_apps] if eligible_apps else []

        screening_run_id = _new_id()

        # Record the screening run state in MongoDB first (so worker always finds the run)
        db["screening_runs"].insert_one({
            "_id": screening_run_id,
            "screening_run_id": screening_run_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "status": "QUEUED",
            "phase2_status": "NOT_STARTED",
            "phase3_status": "NOT_STARTED",
            "eligible_candidate_count": indexed_count,
            "input_application_ids": input_application_ids,
            "initiated_by_sub": auth.user_sub,
            "created_at": _now_iso(),
        })

        # Push to SQS — the ScreeningWorker Lambda will execute Phase 2+3
        sqs = boto3.client("sqs")
        queue_url = os.environ.get("SCREENING_QUEUE_URL", "")
        if queue_url:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "screening_run_id": screening_run_id,
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                }),
            )

    logger.info(
        "Queued screening run %s (job: %s, eligible: %d, by: %s)",
        screening_run_id, job_id, indexed_count, auth.user_sub,
    )
    return _response(202, {
        "screening_run_id": screening_run_id,
        "status": "QUEUED",
        "eligible_candidate_count": indexed_count,
        "message": "Screening started. Poll GET /jobs/{job_id}/screening-results for updates.",
    })


def _get_screening_results(event: dict) -> dict:
    """
    GET /jobs/{job_id}/screening-results  [PROTECTED — requires MEMBER role]
    Returns the latest screening run results for this job.

    Tenant isolation: resolves job → trusted tenant_id, then verifies caller
    is a member of that tenant before returning results.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]

        # Resolve the job's authoritative tenant — never trust the caller
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        # Authorization: verify caller is MEMBER of the job's owning tenant
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        # Scoped query: filter by both job_id AND tenant_id
        run = db["screening_runs"].find_one(
            {"job_id": job_id, "tenant_id": tenant_id},
            {"_id": 0},
            sort=[("created_at", -1)],
        )

    if not run:
        return _response(404, {"error": "No screening run found for this job."})

    return _response(200, run)


def _get_me(event: dict) -> dict:
    """
    GET /me  [PROTECTED — requires valid JWT]
    Returns the authenticated user's identity and list of tenant memberships.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        memberships = list(db["tenant_memberships"].find({"user_sub": auth.user_sub}, {"_id": 0}))

        tenants_list = []
        for m in memberships:
            tid = m["tenant_id"]
            tenant_doc = db["tenants"].find_one({"_id": tid}, {"name": 1, "status": 1})
            tenants_list.append({
                "tenant_id": tid,
                "name": tenant_doc.get("name", "Unknown") if tenant_doc else "Unknown",
                "role": m.get("role", "MEMBER"),
                "status": tenant_doc.get("status", "ACTIVE") if tenant_doc else "INACTIVE",
            })

    return _response(200, {
        "user_sub": auth.user_sub,
        "email": auth.email,
        "username": auth.username,
        "tenants": tenants_list,
    })


def _get_public_job(event: dict) -> dict:
    """
    GET /jobs/{job_id}  [PUBLIC — Candidate Portal]
    Returns public job posting details without revealing tenant or internal data.
    """
    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id})

    if not job:
        return _response(404, {"error": "Job not found."})

    return _response(200, {
        "job_id": job.get("job_id", job.get("_id")),
        "title": job.get("title", ""),
        "description": job.get("description", ""),
        "status": job.get("status", "OPEN"),
        "created_at": job.get("created_at"),
    })


def _patch_job(event: dict) -> dict:
    """
    PATCH /jobs/{job_id}  [PROTECTED — requires ADMIN role in owning tenant]
    Updates job title, description, or status (OPEN / CLOSED).
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    body = json.loads(event.get("body") or "{}")
    allowed_fields = ["title", "description", "status"]
    update_data = {}

    for field in allowed_fields:
        if field in body:
            val = body[field]
            if field == "status" and val not in ["OPEN", "CLOSED", "ARCHIVED"]:
                return _response(400, {
                    "error": "Field 'status' must be 'OPEN', 'CLOSED', or 'ARCHIVED'.",
                    "code": "INVALID_STATUS",
                })
            if field == "title" and not str(val).strip():
                return _response(400, {"error": "Field 'title' cannot be empty."})
            update_data[field] = val.strip() if isinstance(val, str) else val

    if not update_data:
        return _response(400, {
            "error": "At least one of 'title', 'description', or 'status' must be provided.",
        })

    update_data["updated_at"] = _now_iso()

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="ADMIN"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have admin access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        db["jobs"].update_one({"_id": job_id}, {"$set": update_data})
        updated_job = db["jobs"].find_one({"_id": job_id}, {"_id": 0})

    return _response(200, updated_job)


def _get_applications(event: dict) -> dict:
    """
    GET /jobs/{job_id}/applications  [PROTECTED — requires MEMBER role in owning tenant]
    Lists applications for the job with pagination and optional status filter.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    qs = event.get("queryStringParameters") or {}
    try:
        limit = min(max(int(qs.get("limit", 50)), 1), 100)
        skip = max(int(qs.get("skip", 0)), 0)
    except ValueError:
        return _response(400, {"error": "Parameters 'limit' and 'skip' must be valid integers."})

    status_filter = qs.get("status")

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        query: dict[str, Any] = {"job_id": job_id, "tenant_id": tenant_id}
        if status_filter:
            query["status"] = status_filter

        total = db["applications"].count_documents(query)
        cursor = db["applications"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        apps = list(cursor)

    return _response(200, {
        "job_id": job_id,
        "total": total,
        "limit": limit,
        "skip": skip,
        "applications": apps,
    })


def _get_application(event: dict) -> dict:
    """
    GET /jobs/{job_id}/applications/{application_id}  [PROTECTED — requires MEMBER role]
    Returns single application detail and resume processing status.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    params = event.get("pathParameters") or {}
    job_id = params.get("job_id")
    app_id = params.get("application_id")
    if not job_id or not app_id:
        return _response(400, {"error": "job_id and application_id path parameters required."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        app = db["applications"].find_one(
            {"_id": app_id, "job_id": job_id, "tenant_id": tenant_id},
            {"_id": 0},
        )

    if not app:
        return _response(404, {"error": "Application not found."})

    return _response(200, app)


def _get_screening_run_by_id(event: dict) -> dict:
    """
    GET /screening-runs/{screening_run_id}  [PROTECTED — requires MEMBER role in owning tenant]
    Returns screening run details by run ID.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    run_id = (event.get("pathParameters") or {}).get("screening_run_id")
    if not run_id:
        return _response(400, {"error": "screening_run_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        run = db["screening_runs"].find_one({"_id": run_id}, {"_id": 0})
        if not run:
            return _response(404, {"error": "Screening run not found."})

        tenant_id = run.get("tenant_id")
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this screening run's tenant.",
                "code": "FORBIDDEN",
            })

    return _response(200, run)


def _get_tenant_members(event: dict) -> dict:
    """
    GET /tenants/{tenant_id}/members  [PROTECTED — requires MEMBER role]
    Returns members of the tenant.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    tenant_id = (event.get("pathParameters") or {}).get("tenant_id")
    if not tenant_id:
        return _response(400, {"error": "tenant_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this tenant.",
                "code": "FORBIDDEN",
            })

        members = list(db["tenant_memberships"].find({"tenant_id": tenant_id}, {"_id": 0}))

    return _response(200, {"tenant_id": tenant_id, "members": members})


def _post_tenant_member(event: dict) -> dict:
    """
    POST /tenants/{tenant_id}/members  [PROTECTED — requires ADMIN role]
    Adds or updates a member's role in the tenant.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    tenant_id = (event.get("pathParameters") or {}).get("tenant_id")
    if not tenant_id:
        return _response(400, {"error": "tenant_id path parameter missing."})

    body = json.loads(event.get("body") or "{}")
    user_sub = body.get("user_sub", "").strip()
    role = body.get("role", "MEMBER").strip().upper()

    if not user_sub:
        return _response(400, {"error": "Field 'user_sub' is required."})
    if role not in ["MEMBER", "ADMIN"]:
        return _response(400, {"error": "Field 'role' must be 'MEMBER' or 'ADMIN'."})

    now = _now_iso()

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="ADMIN"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have admin access to this tenant.",
                "code": "FORBIDDEN",
            })

        member_id = f"{user_sub}:{tenant_id}"
        db["tenant_memberships"].update_one(
            {"_id": member_id},
            {
                "$set": {
                    "user_sub": user_sub,
                    "tenant_id": tenant_id,
                    "role": role,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )

    return _response(201, {
        "tenant_id": tenant_id,
        "user_sub": user_sub,
        "role": role,
    })


def _get_candidate_application_status(event: dict) -> dict:
    """
    GET /jobs/{job_id}/applications/{application_id}/status  [PUBLIC — Candidate Portal]
    Returns applicant's processing status without exposing recruiter or candidate PII.
    """
    params = event.get("pathParameters") or {}
    job_id = params.get("job_id")
    app_id = params.get("application_id")
    if not job_id or not app_id:
        return _response(400, {"error": "job_id and application_id path parameters required."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        app = db["applications"].find_one({"_id": app_id, "job_id": job_id})

    if not app:
        return _response(404, {"error": "Application not found."})

    return _response(200, {
        "application_id": app_id,
        "job_id": job_id,
        "status": app.get("status", "PENDING_UPLOAD"),
        "phase1_status": app.get("phase1_status", "NOT_STARTED"),
        "phase2_status": app.get("phase2_status", "NOT_STARTED"),
        "created_at": app.get("created_at"),
    })


def _delete_job(event: dict) -> dict:
    """
    DELETE /jobs/{job_id}  [PROTECTED — requires ADMIN role in owning tenant]
    Safely archives a job (soft delete) to preserve application and screening audit trails.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="ADMIN"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have admin access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        db["jobs"].update_one(
            {"_id": job_id},
            {"$set": {"status": "ARCHIVED", "updated_at": _now_iso()}},
        )

    return _response(200, {
        "job_id": job_id,
        "status": "ARCHIVED",
        "message": "Job successfully archived.",
    })


def _delete_application(event: dict) -> dict:
    """
    DELETE /jobs/{job_id}/applications/{application_id}  [PROTECTED — requires MEMBER role]
    Safely archives an application (soft delete) while preserving audit logs.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    params = event.get("pathParameters") or {}
    job_id = params.get("job_id")
    app_id = params.get("application_id")
    if not job_id or not app_id:
        return _response(400, {"error": "job_id and application_id path parameters required."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        tenant_id = _resolve_job_tenant(db, job_id)
        if not tenant_id:
            return _response(404, {"error": "Job not found."})

        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="MEMBER"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have access to this job's tenant.",
                "code": "FORBIDDEN",
            })

        res = db["applications"].update_one(
            {"_id": app_id, "job_id": job_id, "tenant_id": tenant_id},
            {"$set": {"status": "ARCHIVED", "updated_at": _now_iso()}},
        )
        if res.matched_count == 0:
            return _response(404, {"error": "Application not found."})

    return _response(200, {
        "application_id": app_id,
        "status": "ARCHIVED",
        "message": "Application successfully archived.",
    })


def _delete_tenant_member(event: dict) -> dict:
    """
    DELETE /tenants/{tenant_id}/members/{user_sub}  [PROTECTED — requires ADMIN role]
    Revokes a user's membership in the tenant organization.
    Guards against revoking the sole remaining administrator.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    params = event.get("pathParameters") or {}
    tenant_id = params.get("tenant_id")
    target_sub = params.get("user_sub")
    if not tenant_id or not target_sub:
        return _response(400, {"error": "tenant_id and user_sub path parameters required."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        membership = require_tenant_access(
            db["tenant_memberships"], auth, tenant_id, minimum_role="ADMIN"
        )
        if not membership:
            return _response(403, {
                "error": "You do not have admin access to this tenant.",
                "code": "FORBIDDEN",
            })

        target_membership = db["tenant_memberships"].find_one(
            {"user_sub": target_sub, "tenant_id": tenant_id}
        )
        if not target_membership:
            return _response(404, {"error": "Membership not found."})

        if target_membership.get("role") == "ADMIN":
            admin_count = db["tenant_memberships"].count_documents(
                {"tenant_id": tenant_id, "role": "ADMIN"}
            )
            if admin_count <= 1:
                return _response(400, {
                    "error": "Cannot revoke membership: this user is the sole administrator of the tenant.",
                    "code": "LAST_ADMIN_PROTECTION",
                })

        db["tenant_memberships"].delete_one({"user_sub": target_sub, "tenant_id": tenant_id})

    return _response(200, {
        "tenant_id": tenant_id,
        "user_sub": target_sub,
        "message": "Membership revoked successfully.",
    })


# ─── Router ────────────────────────────────────────────────────────────────────

_ROUTES = {
    # ── Recruiter Workspace (Protected — requires Cognito JWT) ────────────────
    ("GET",    "/me"):                                             _get_me,
    ("POST",   "/tenants"):                                        _post_tenant,
    ("POST",   "/tenants/{tenant_id}/jobs"):                       _post_job,
    ("GET",    "/tenants/{tenant_id}/jobs"):                       _get_jobs,
    ("GET",    "/tenants/{tenant_id}/jobs/{job_id}"):              _get_job,
    ("PATCH",  "/jobs/{job_id}"):                                  _patch_job,
    ("DELETE", "/jobs/{job_id}"):                                  _delete_job,
    ("GET",    "/jobs/{job_id}/applications"):                     _get_applications,
    ("GET",    "/jobs/{job_id}/applications/{application_id}"):    _get_application,
    ("DELETE", "/jobs/{job_id}/applications/{application_id}"):    _delete_application,
    ("POST",   "/jobs/{job_id}/screening"):                        _post_screening,
    ("GET",    "/jobs/{job_id}/screening-results"):                _get_screening_results,
    ("GET",    "/screening-runs/{screening_run_id}"):              _get_screening_run_by_id,
    ("GET",    "/tenants/{tenant_id}/members"):                    _get_tenant_members,
    ("POST",   "/tenants/{tenant_id}/members"):                    _post_tenant_member,
    ("DELETE", "/tenants/{tenant_id}/members/{user_sub}"):         _delete_tenant_member,

    # ── Candidate Portal (Public — no auth) ────────────────────────────────────
    ("GET",    "/jobs/{job_id}"):                                  _get_public_job,
    ("POST",   "/jobs/{job_id}/applications"):                     _post_application,
    ("GET",    "/jobs/{job_id}/applications/{application_id}/status"): _get_candidate_application_status,
}


def lambda_handler(event: dict, context: object) -> dict:
    """Main Lambda entry point — routes API Gateway events to handlers."""
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    handler = _ROUTES.get((method, resource))
    if handler is None:
        return _response(404, {"error": f"Route not found: {method} {resource}"})

    try:
        return handler(event)
    except Exception as exc:
        logger.error("Handler error on %s %s: %s", method, resource, exc)
        return _response(500, {"error": "Internal server error."})
