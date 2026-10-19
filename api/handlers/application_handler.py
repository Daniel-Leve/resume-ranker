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

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
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
S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "mock-s3-bucket")
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
    raw_count = (
        body.get("final_shortlisted_candidates_count")
        or body.get("shortlisted_candidates_count")
        or body.get("shortlisted_count")
    )
    shortlisted_count = 5
    if raw_count is not None:
        try:
            val = int(raw_count)
            if val > 0:
                shortlisted_count = val
            else:
                return _response(400, {"error": "Field 'final_shortlisted_candidates_count' must be a positive integer."})
        except (ValueError, TypeError):
            return _response(400, {"error": "Field 'final_shortlisted_candidates_count' must be a valid integer."})

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
            "final_shortlisted_candidates_count": shortlisted_count,
            "status": "OPEN",
            "created_at": _now_iso(),
            "application_count": 0,
        }
        db["jobs"].insert_one(doc)

    logger.info("Created job %s (tenant: %s, shortlisted: %d)", job_id, tenant_id_from_path, shortlisted_count)
    return _response(201, {
        "job_id": job_id,
        "tenant_id": tenant_id_from_path,
        "title": title,
        "final_shortlisted_candidates_count": shortlisted_count,
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

    # Generate secure candidate access token for candidate portal authentication
    candidate_access_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(candidate_access_token.encode("utf-8")).hexdigest()

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
        "candidate_access_token_hash": token_hash,
        "decision": "UNDECIDED",
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
        "candidate_access_token": candidate_access_token,
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
        job = db["jobs"].find_one({"_id": job_id})
        if not job:
            return _response(404, {"error": "Job not found."})
        tenant_id = job.get("tenant_id")
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

        if job.get("status") == "ARCHIVED":
            return _response(409, {
                "error": "Cannot trigger screening on an archived job.",
                "code": "JOB_ARCHIVED",
            })

        # Guard: Check rubric approval if rubric is configured for this job
        rubric_status = job.get("rubric_status")
        if rubric_status == "DRAFT":
            return _response(400, {
                "error": "The rubric for this job is in DRAFT status. Please approve the rubric via POST /jobs/{job_id}/rubric/approve before running screening.",
                "code": "RUBRIC_NOT_APPROVED"
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

        # Guard against premature screening: check for indexed applications (excluding archived)
        indexed_count = db["applications"].count_documents({
            "job_id": job_id,
            "tenant_id": tenant_id,
            "phase2_status": "INDEXED",
            "status": {"$ne": "ARCHIVED"},
        })
        if indexed_count == 0:
            total_count = db["applications"].count_documents({
                "job_id": job_id,
                "tenant_id": tenant_id,
                "status": {"$ne": "ARCHIVED"},
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
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "phase2_status": "INDEXED",
                "status": {"$ne": "ARCHIVED"},
            },
            {"_id": 1}
        )) if hasattr(db["applications"], "find") else []
        input_application_ids = [str(app["_id"]) for app in eligible_apps] if eligible_apps else []

        screening_run_id = _new_id()

        body = json.loads(event.get("body") or "{}") if event.get("body") else {}
        shortlisted_override = (
            body.get("final_shortlisted_candidates_count")
            or body.get("shortlisted_candidates_count")
            or body.get("shortlisted_count")
        )
        if shortlisted_override is not None:
            try:
                shortlisted_count = max(1, int(shortlisted_override))
            except (ValueError, TypeError):
                shortlisted_count = job.get("final_shortlisted_candidates_count", 5)
        else:
            shortlisted_count = job.get("final_shortlisted_candidates_count", 5)
        try:
            shortlisted_count = max(1, int(shortlisted_count))
        except (ValueError, TypeError):
            shortlisted_count = 5

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
            "final_shortlisted_candidates_count": shortlisted_count,
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
                    "final_shortlisted_candidates_count": shortlisted_count,
                }),
            )

    logger.info(
        "Queued screening run %s (job: %s, eligible: %d, final_shortlisted: %d, by: %s)",
        screening_run_id, job_id, indexed_count, shortlisted_count, auth.user_sub,
    )
    return _response(202, {
        "screening_run_id": screening_run_id,
        "status": "QUEUED",
        "eligible_candidate_count": indexed_count,
        "final_shortlisted_candidates_count": shortlisted_count,
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


# ─── Phase 4: Rubric, Explainability & Review Queue Handlers ──────────────────

def _post_job_rubric(event: dict) -> dict:
    """
    POST /jobs/{job_id}/rubric  [PROTECTED — requires ADMIN role]
    Generates a draft rubric from the job description using LLM.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id})
        if not job:
            return _response(404, {"error": f"Job {job_id} not found."})

        tenant_id = job.get("tenant_id")
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

        jd_text = job.get("description", "")
        if not jd_text.strip():
            return _response(400, {"error": "Job description is empty. Cannot build rubric."})

        from phase4.llm_client import GroqClient
        from phase4.rubric_builder import build_rubric

        # Versioning: if rubric already APPROVED, automatically create next version (v2, v3, ...)
        current_status = job.get("rubric_status")
        current_rubric = job.get("rubric") or {}
        rubric_history = list(job.get("rubric_history") or [])

        version_to_build = "v1"
        if current_status == "APPROVED" or current_rubric.get("status") == "APPROVED":
            rubric_history.append(current_rubric)
            cur_ver = current_rubric.get("version", "v1")
            parts = cur_ver.split("v")
            version_to_build = f"v{int(parts[1]) + 1}" if len(parts) == 2 and parts[1].isdigit() else "v2"

        client_llm = GroqClient()
        rubric = build_rubric(jd_text=jd_text, jd_id=job_id, llm_client=client_llm, version=version_to_build)

        update_fields: dict[str, Any] = {
            "rubric": rubric.model_dump(),
            "rubric_status": "DRAFT",
            "rubric_updated_at": _now_iso(),
        }
        if rubric_history:
            update_fields["rubric_history"] = rubric_history

        db["jobs"].update_one(
            {"_id": job_id, "tenant_id": tenant_id},
            {"$set": update_fields}
        )

    return _response(200, rubric.model_dump())


def _get_job_rubric(event: dict) -> dict:
    """
    GET /jobs/{job_id}/rubric  [PROTECTED — requires MEMBER role]
    Returns the current rubric (DRAFT or APPROVED) for a job.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id})
        if not job:
            return _response(404, {"error": f"Job {job_id} not found."})

        tenant_id = job.get("tenant_id")
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

        if "rubric" in job and job["rubric"]:
            return _response(200, job["rubric"])

        # Check local disk
        from phase4.rubric_builder import get_rubric
        disk_rubric = get_rubric(job_id)
        if disk_rubric:
            return _response(200, disk_rubric.model_dump())

    return _response(404, {"error": "No rubric found for this job. Call POST /jobs/{job_id}/rubric to generate one."})


def _post_approve_rubric(event: dict) -> dict:
    """
    POST /jobs/{job_id}/rubric/approve  [PROTECTED — requires ADMIN role]
    Approves the rubric, transitioning it to APPROVED status.
    Approved rubrics are immutable; modifications require creating a new rubric version.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    body = json.loads(event.get("body") or "{}") if event.get("body") else {}
    custom_criteria = body.get("criteria")

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id})
        if not job:
            return _response(404, {"error": f"Job {job_id} not found."})

        tenant_id = job.get("tenant_id")
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

        from phase4.rubric_builder import approve_rubric, JobRubric

        # Immutability check: if already APPROVED, disallow modifying criteria
        if job.get("rubric_status") == "APPROVED" or (job.get("rubric") and job["rubric"].get("status") == "APPROVED"):
            current_criteria = (job.get("rubric") or {}).get("criteria", [])
            if custom_criteria and custom_criteria != current_criteria:
                return _response(409, {
                    "error": "Rubric is already APPROVED and immutable. Generate a new rubric version to modify criteria.",
                    "code": "RUBRIC_ALREADY_APPROVED",
                })
            return _response(200, job["rubric"])

        if "rubric" in job and job["rubric"]:
            rubric_dict = dict(job["rubric"])
            if custom_criteria:
                rubric_dict["criteria"] = custom_criteria
            rubric_obj = JobRubric.model_validate(rubric_dict)
            rubric_obj.status = "APPROVED"
            rubric_obj.approved_at = _now_iso()
            rubric_obj.approved_by = auth.user_sub

            db["jobs"].update_one(
                {"_id": job_id, "tenant_id": tenant_id},
                {"$set": {
                    "rubric": rubric_obj.model_dump(),
                    "rubric_status": "APPROVED",
                    "rubric_approved_at": rubric_obj.approved_at,
                    "rubric_approved_by": rubric_obj.approved_by,
                }}
            )
            try:
                approve_rubric(job_id, approved_by=auth.user_sub, custom_criteria=custom_criteria, version=rubric_obj.version)
            except Exception:
                pass
            return _response(200, rubric_obj.model_dump())
        else:
            try:
                approved = approve_rubric(job_id, approved_by=auth.user_sub, custom_criteria=custom_criteria)
                db["jobs"].update_one(
                    {"_id": job_id, "tenant_id": tenant_id},
                    {"$set": {
                        "rubric": approved.model_dump(),
                        "rubric_status": "APPROVED",
                        "rubric_approved_at": approved.approved_at,
                        "rubric_approved_by": approved.approved_by,
                    }}
                )
                return _response(200, approved.model_dump())
            except Exception as exc:
                return _response(400, {"error": f"Cannot approve rubric: {exc}"})


def _get_screening_status(event: dict) -> dict:
    """
    GET /jobs/{job_id}/screening-status  [PROTECTED — requires MEMBER role]
    Live dashboard widget returning screening counts, progress, daily budget, and ETA.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id})
        if not job:
            return _response(404, {"error": f"Job {job_id} not found."})

        tenant_id = job.get("tenant_id")
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

        latest_run = db["screening_runs"].find_one(
            {"job_id": job_id, "tenant_id": tenant_id},
            sort=[("created_at", -1)],
        )

        total_apps = db["applications"].count_documents({"job_id": job_id, "tenant_id": tenant_id, "status": {"$ne": "ARCHIVED"}}) if hasattr(db["applications"], "count_documents") else 0
        indexed_apps = db["applications"].count_documents({"job_id": job_id, "tenant_id": tenant_id, "phase2_status": "INDEXED", "status": {"$ne": "ARCHIVED"}}) if hasattr(db["applications"], "count_documents") else 0

        from phase4.daily_budget import DailyBudget
        from phase4.review_queue import GLOBAL_REVIEW_QUEUE, ReviewQueueManager

        budget_info = DailyBudget(mongo_db=db).get_budget_status()
        rq_mgr = ReviewQueueManager(mongo_db=db)
        db_items = rq_mgr.list_items(job_id=job_id, status="NEEDS_REVIEW", tenant_id=tenant_id)
        pending_review_count = len(db_items) if db_items else len(GLOBAL_REVIEW_QUEUE.list_items(job_id=job_id, status="NEEDS_REVIEW"))

    shortlisted_target = job.get("final_shortlisted_candidates_count", 5)
    run_status = latest_run.get("status") if latest_run else "NOT_STARTED"
    candidate_count = latest_run.get("candidate_count", 0) if latest_run else 0
    phase2_count = latest_run.get("phase2_candidate_count", 0) if latest_run else 0

    return _response(200, {
        "job_id": job_id,
        "screening_run_status": run_status,
        "target_shortlisted_count": shortlisted_target,
        "candidates_shortlisted": candidate_count,
        "candidates_evaluated_phase2": phase2_count,
        "total_applications": total_apps,
        "indexed_applications": indexed_apps,
        "review_queue_pending": pending_review_count,
        "daily_budget": budget_info,
        "rubric_status": job.get("rubric_status", "NOT_CONFIGURED"),
    })


def _get_candidate_report(event: dict) -> dict:
    """
    GET /jobs/{job_id}/candidates/{candidate_id}/report  [PROTECTED — requires MEMBER role]
    Returns the comprehensive HR shortlist report for a candidate.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    path_params = event.get("pathParameters") or {}
    job_id = path_params.get("job_id")
    candidate_id = path_params.get("candidate_id")
    if not job_id or not candidate_id:
        return _response(400, {"error": "job_id and candidate_id path parameters are required."})

    from phase4 import config
    json_path = config.REPORTS_DIR / job_id / f"hr_report_{candidate_id}.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return _response(200, json.load(f))
        except Exception:
            pass

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id})
        if not job:
            return _response(404, {"error": f"Job {job_id} not found."})

        tenant_id = job.get("tenant_id")
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

        run = db["screening_runs"].find_one(
            {"job_id": job_id, "tenant_id": tenant_id, "status": "COMPLETED"},
            sort=[("completed_at", -1)],
        )
        if run and "candidates" in run:
            for cand in run["candidates"]:
                if cand.get("candidate_id") == candidate_id or cand.get("application_id") == candidate_id:
                    if "explanation" in cand:
                        return _response(200, cand["explanation"])
                    elif "hr_report" in cand:
                        return _response(200, cand["hr_report"])

    return _response(404, {"error": f"Report not found for candidate {candidate_id} in job {job_id}."})


def _get_review_queue(event: dict) -> dict:
    """
    GET /jobs/{job_id}/review-queue  [PROTECTED — requires MEMBER role in owning tenant]
    Lists items requiring human recruiter review for a job.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    status_filter = (event.get("queryStringParameters") or {}).get("status", "NEEDS_REVIEW")

    try:
        with _get_mongo() as client:
            db = client[MONGODB_DATABASE]
            job = db["jobs"].find_one({"_id": job_id})
            if not job:
                return _response(404, {"error": f"Job {job_id} not found."})

            tenant_id = job.get("tenant_id")
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

            from phase4.review_queue import GLOBAL_REVIEW_QUEUE, ReviewQueueManager
            rq_mgr = ReviewQueueManager(mongo_db=db)
            items = rq_mgr.list_items(job_id=job_id, status=status_filter, tenant_id=tenant_id)
            if not items:
                items = GLOBAL_REVIEW_QUEUE.list_items(job_id=job_id, status=status_filter)

        return _response(200, {
            "job_id": job_id,
            "count": len(items),
            "items": [item.model_dump() for item in items],
        })
    except Exception as exc:
        logger.warning("MongoDB access failed in _get_review_queue (%s), using local fallback.", exc)
        from phase4.review_queue import GLOBAL_REVIEW_QUEUE
        items = GLOBAL_REVIEW_QUEUE.list_items(job_id=job_id, status=status_filter)
        return _response(200, {
            "job_id": job_id,
            "count": len(items),
            "items": [item.model_dump() for item in items],
        })


def _post_review_queue_action(event: dict) -> dict:
    """
    POST /jobs/{job_id}/review-queue/{candidate_id}/action  [PROTECTED — requires MEMBER role in owning tenant]
    Resolves a review item with action: promote | confirm_reject | fix_rubric.
    """
    auth, err = _require_auth(event)
    if err:
        return err

    path_params = event.get("pathParameters") or {}
    job_id = path_params.get("job_id")
    candidate_id = path_params.get("candidate_id")
    if not job_id or not candidate_id:
        return _response(400, {"error": "job_id and candidate_id path parameters are required."})

    body = json.loads(event.get("body") or "{}") if event.get("body") else {}
    action = body.get("action")
    if action not in ("promote", "confirm_reject", "fix_rubric"):
        return _response(400, {"error": "Field 'action' must be one of: promote, confirm_reject, fix_rubric."})

    notes = body.get("notes")

    try:
        with _get_mongo() as client:
            db = client[MONGODB_DATABASE]
            job = db["jobs"].find_one({"_id": job_id})
            if not job:
                return _response(404, {"error": f"Job {job_id} not found."})

            tenant_id = job.get("tenant_id")
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

            from phase4.review_queue import GLOBAL_REVIEW_QUEUE, ReviewQueueManager
            rq_mgr = ReviewQueueManager(mongo_db=db)
            try:
                resolved = rq_mgr.resolve(
                    resume_id=candidate_id,
                    action=action,
                    notes=notes,
                    resolved_by=auth.user_sub,
                    job_id=job_id,
                    tenant_id=tenant_id,
                )
                return _response(200, resolved.model_dump())
            except KeyError:
                resolved = GLOBAL_REVIEW_QUEUE.resolve(
                    resume_id=candidate_id,
                    action=action,
                    notes=notes,
                    resolved_by=auth.user_sub,
                )
                return _response(200, resolved.model_dump())
    except KeyError:
        return _response(404, {"error": f"Candidate {candidate_id} not found in review queue."})
    except Exception as exc:
        logger.warning("MongoDB access failed in _post_review_queue_action (%s), using local fallback.", exc)
        from phase4.review_queue import GLOBAL_REVIEW_QUEUE
        try:
            resolved = GLOBAL_REVIEW_QUEUE.resolve(
                resume_id=candidate_id,
                action=action,
                notes=notes,
                resolved_by=auth.user_sub,
            )
            return _response(200, resolved.model_dump())
        except KeyError:
            return _response(404, {"error": f"Candidate {candidate_id} not found in review queue."})
        except Exception as inner_exc:
            return _response(500, {"error": f"Failed to resolve review item: {inner_exc}"})


def _get_candidate_feedback(event: dict) -> dict:
    """
    GET /jobs/{job_id}/applications/{application_id}/feedback  [PUBLIC — Candidate Portal with access token or Recruiter JWT]
    Returns constructive candidate feedback ONLY when an authoritative decision has confirmed REJECTED status.
    Guards:
      1. Validates candidate access token (X-Application-Token header or ?token=) or recruiter JWT.
      2. Ensures authoritative decision integrity (UNDECIDED / in-review returns 409).
      3. SHORTLISTED candidates receive congratulatory status, never rejection feedback.
      4. Strips internal scores, ranks, rubric weights, and recruiter reports from payload.
    """
    path_params = event.get("pathParameters") or {}
    job_id = path_params.get("job_id")
    application_id = path_params.get("application_id")
    if not job_id or not application_id:
        return _response(400, {"error": "job_id and application_id path parameters are required."})

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    candidate_token = (
        headers.get("x-application-token")
        or headers.get("x-candidate-token")
        or (event.get("queryStringParameters") or {}).get("token")
        or (event.get("queryStringParameters") or {}).get("access_token")
    )
    if not candidate_token and headers.get("authorization", "").startswith("Bearer "):
        token_part = headers["authorization"].split("Bearer ", 1)[1].strip()
        if not token_part.startswith("eyJ"):  # Not a JWT
            candidate_token = token_part

    recruiter_auth = None
    if not candidate_token:
        recruiter_auth, _ = _require_auth(event)

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        app = db["applications"].find_one({"_id": application_id, "job_id": job_id})
        if not app:
            return _response(404, {"error": "Application not found."})

        tenant_id = app.get("tenant_id")

        # Credential Verification
        is_authorized = False
        if recruiter_auth and tenant_id:
            membership = require_tenant_access(
                db["tenant_memberships"], recruiter_auth, tenant_id, minimum_role="MEMBER"
            )
            if membership:
                is_authorized = True

        expected_hash = app.get("candidate_access_token_hash")
        if not is_authorized and candidate_token:
            if expected_hash:
                provided_hash = hashlib.sha256(candidate_token.strip().encode("utf-8")).hexdigest()
                if hmac.compare_digest(provided_hash, expected_hash):
                    is_authorized = True
            else:
                # Legacy app without stored token hash
                is_authorized = True

        if not is_authorized:
            if candidate_token:
                return _response(403, {"error": "Forbidden: Invalid application access token.", "code": "INVALID_TOKEN"})
            return _response(401, {
                "error": "Unauthorized: Valid candidate access token (X-Application-Token) or recruiter credentials required.",
                "code": "AUTHENTICATION_REQUIRED",
            })

        # Decision Integrity Guard
        decision = app.get("decision")
        if not decision:
            decision = "REJECTED" if "candidate_feedback" in app else app.get("status")

        if decision == "SHORTLISTED":
            return _response(200, {
                "application_id": application_id,
                "job_id": job_id,
                "decision_status": "SHORTLISTED",
                "message": "Congratulations! Your application has been shortlisted for further consideration.",
            })

        if decision not in ("REJECTED", "CONFIRMED_REJECT"):
            return _response(409, {
                "application_id": application_id,
                "job_id": job_id,
                "decision_status": decision or "UNDECIDED",
                "message": "Application review is still underway. Constructive feedback will be published once an authoritative decision is confirmed.",
                "code": "DECISION_PENDING",
            })

        # Confirmed REJECTED — return strictly sanitized candidate feedback
        from phase4.privacy import sanitize_candidate_feedback

        raw_feedback_text = None
        if "candidate_feedback" in app:
            fb = app["candidate_feedback"]
            if isinstance(fb, dict):
                raw_feedback_text = fb.get("feedback_markdown") or fb.get("feedback_text")
                if not raw_feedback_text and "gaps" in fb:
                    raw_feedback_text = f"## Strengths\n{fb.get('what_resume_showed', '')}\n\n## Areas for Growth\n" + "\n".join(f"- {g}" for g in fb.get("gaps", []))
            elif isinstance(fb, str):
                raw_feedback_text = fb

        if not raw_feedback_text:
            from phase4 import config
            fb_path = config.FEEDBACK_DIR / f"{application_id}.md"
            if fb_path.exists():
                try:
                    raw_feedback_text = fb_path.read_text(encoding="utf-8")
                except Exception:
                    pass

        if not raw_feedback_text:
            return _response(404, {"error": "Feedback content not yet generated for this rejected application."})

        sanitized_feedback = sanitize_candidate_feedback(raw_feedback_text)
        payload = {
            "application_id": application_id,
            "job_id": job_id,
            "decision_status": "REJECTED",
            "feedback_markdown": sanitized_feedback,
        }
        if isinstance(app.get("candidate_feedback"), dict):
            if "gaps" in app["candidate_feedback"]:
                payload["gaps"] = app["candidate_feedback"]["gaps"]
            if "what_resume_showed" in app["candidate_feedback"]:
                payload["what_resume_showed"] = app["candidate_feedback"]["what_resume_showed"]
        return _response(200, payload)


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
    allowed_fields = [
        "title",
        "description",
        "status",
        "final_shortlisted_candidates_count",
        "shortlisted_candidates_count",
        "shortlisted_count",
    ]
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
            if field in ["final_shortlisted_candidates_count", "shortlisted_candidates_count", "shortlisted_count"]:
                try:
                    c_val = int(val)
                    if c_val <= 0:
                        return _response(400, {"error": "Field 'final_shortlisted_candidates_count' must be a positive integer."})
                    update_data["final_shortlisted_candidates_count"] = c_val
                except (ValueError, TypeError):
                    return _response(400, {"error": "Field 'final_shortlisted_candidates_count' must be a valid integer."})
                continue
            update_data[field] = val.strip() if isinstance(val, str) else val

    if not update_data:
        return _response(400, {
            "error": "At least one of 'title', 'description', 'status', or 'final_shortlisted_candidates_count' must be provided.",
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
        "s3_uploaded": bool(app.get("s3_resume_key")),
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

    # ── Phase 4 Explainability & Rubric Management (Protected) ───────────────
    ("POST",   "/jobs/{job_id}/rubric"):                           _post_job_rubric,
    ("GET",    "/jobs/{job_id}/rubric"):                           _get_job_rubric,
    ("POST",   "/jobs/{job_id}/rubric/approve"):                   _post_approve_rubric,
    ("GET",    "/jobs/{job_id}/screening-status"):                 _get_screening_status,
    ("GET",    "/jobs/{job_id}/candidates/{candidate_id}/report"): _get_candidate_report,
    ("GET",    "/jobs/{job_id}/review-queue"):                     _get_review_queue,
    ("POST",   "/jobs/{job_id}/review-queue/{candidate_id}/action"): _post_review_queue_action,

    # ── Candidate Portal (Public — no auth) ────────────────────────────────────
    ("GET",    "/jobs/{job_id}"):                                  _get_public_job,
    ("POST",   "/jobs/{job_id}/applications"):                     _post_application,
    ("GET",    "/jobs/{job_id}/applications/{application_id}/status"): _get_candidate_application_status,
    ("GET",    "/jobs/{job_id}/applications/{application_id}/feedback"): _get_candidate_feedback,
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
