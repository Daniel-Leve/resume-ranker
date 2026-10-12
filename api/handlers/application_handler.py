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


# ─── Router ────────────────────────────────────────────────────────────────────

_ROUTES = {
    ("POST",  "/tenants"):                            _post_tenant,
    ("POST",  "/tenants/{tenant_id}/jobs"):           _post_job,
    ("GET",   "/tenants/{tenant_id}/jobs"):           _get_jobs,
    ("GET",   "/tenants/{tenant_id}/jobs/{job_id}"):  _get_job,
    ("POST",  "/jobs/{job_id}/applications"):         _post_application,
    ("POST",  "/jobs/{job_id}/screening"):            _post_screening,
    ("GET",   "/jobs/{job_id}/screening-results"):    _get_screening_results,
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
