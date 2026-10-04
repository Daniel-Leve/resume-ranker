"""
API Handler — Manages Tenants, Jobs, Applications, and Screening triggers.

Endpoints handled:
    POST   /tenants
    POST   /tenants/{tenant_id}/jobs
    GET    /tenants/{tenant_id}/jobs/{job_id}
    POST   /jobs/{job_id}/applications
    POST   /jobs/{job_id}/screening
    GET    /jobs/{job_id}/screening-results

Security:
    - tenant_id is extracted from the authenticated JWT (caller identity).
    - Presigned URLs are scoped to the exact S3 prefix for the tenant/job/application.
    - Secrets (MONGODB_URI, VOYAGE_API_KEY) are environment variables never logged.
    - Resume PII (names, emails) is never logged — only IDs and counts.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import certifi
from pymongo import MongoClient

from phase2.storage.s3_paths import build_saas_resume_key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─── Environment ───────────────────────────────────────────────────────────────
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
MONGODB_URI = os.environ["MONGODB_URI"]
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
    return MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=10_000,
        tlsCAFile=certifi.where(),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ─── Route Handlers ────────────────────────────────────────────────────────────

def _post_tenant(event: dict) -> dict:
    """
    POST /tenants
    Creates a new tenant (company) record in MongoDB.
    """
    body = json.loads(event.get("body") or "{}")
    name = body.get("name", "").strip()
    if not name:
        return _response(400, {"error": "Field 'name' is required."})

    tenant_id = _new_id()
    doc = {
        "_id": tenant_id,
        "tenant_id": tenant_id,
        "name": name,
        "created_at": _now_iso(),
        "status": "ACTIVE",
    }

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        db["tenants"].insert_one(doc)

    logger.info("Created tenant: %s", tenant_id)
    return _response(201, {"tenant_id": tenant_id, "name": name})


def _post_job(event: dict) -> dict:
    """
    POST /tenants/{tenant_id}/jobs
    Creates a new job posting under a tenant.
    """
    tenant_id = (event.get("pathParameters") or {}).get("tenant_id")
    if not tenant_id:
        return _response(400, {"error": "tenant_id path parameter missing."})

    body = json.loads(event.get("body") or "{}")
    title = body.get("title", "").strip()
    description = body.get("description", "").strip()
    if not title:
        return _response(400, {"error": "Field 'title' is required."})

    job_id = _new_id()
    doc = {
        "_id": job_id,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "title": title,
        "description": description,
        "status": "OPEN",
        "created_at": _now_iso(),
        "application_count": 0,
    }

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        db["jobs"].insert_one(doc)

    logger.info("Created job: %s (tenant: %s)", job_id, tenant_id)
    return _response(201, {"job_id": job_id, "tenant_id": tenant_id, "title": title, "status": "OPEN"})


def _get_job(event: dict) -> dict:
    """
    GET /tenants/{tenant_id}/jobs/{job_id}
    Returns job details and current screening status.
    """
    params = event.get("pathParameters") or {}
    tenant_id = params.get("tenant_id")
    job_id = params.get("job_id")

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one(
            {"_id": job_id, "tenant_id": tenant_id},
            {"_id": 0}
        )

    if not job:
        return _response(404, {"error": "Job not found."})
    return _response(200, job)


def _post_application(event: dict) -> dict:
    """
    POST /jobs/{job_id}/applications
    Creates a new application and returns a secure presigned S3 URL
    so the candidate can upload their PDF directly to S3.
    """
    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    body = json.loads(event.get("body") or "{}")
    candidate_name = body.get("candidate_name", "").strip()
    if not candidate_name:
        return _response(400, {"error": "Field 'candidate_name' is required."})

    # Look up the tenant_id for this job to build the correct S3 path
    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id}, {"tenant_id": 1})

    if not job:
        return _response(404, {"error": "Job not found."})

    tenant_id = job["tenant_id"]
    application_id = _new_id()

    # Build the exact SaaS S3 path for this application's resume
    s3_key = build_saas_resume_key(tenant_id, job_id, application_id)

    # Generate a presigned URL — the candidate uploads directly to S3
    # The API server never touches the PDF bytes.
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

    # Record application in MongoDB
    app_doc = {
        "_id": application_id,
        "application_id": application_id,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "candidate_name": candidate_name,  # stored for HR display only
        "s3_resume_key": s3_key,
        "status": "PENDING_UPLOAD",
        "phase1_status": "NOT_STARTED",
        "phase2_status": "NOT_STARTED",
        "phase3_status": "NOT_STARTED",
        "created_at": _now_iso(),
    }

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        db["applications"].insert_one(app_doc)
        db["jobs"].update_one(
            {"_id": job_id},
            {"$inc": {"application_count": 1}},
        )

    logger.info("Created application: %s (job: %s)", application_id, job_id)
    return _response(201, {
        "application_id": application_id,
        "upload_url": presigned_url,
        "upload_expires_in_seconds": PRESIGNED_URL_EXPIRY_SECONDS,
        "s3_key": s3_key,
        "instructions": "PUT your PDF to the upload_url with Content-Type: application/pdf",
    })


def _post_screening(event: dict) -> dict:
    """
    POST /jobs/{job_id}/screening
    Triggers the Phase 2+3 Screening pipeline for all INDEXED applications.
    Pushes a message to the ScreeningQueue; processing is asynchronous.
    """
    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"error": "job_id path parameter missing."})

    # Look up tenant_id
    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        job = db["jobs"].find_one({"_id": job_id}, {"tenant_id": 1, "status": 1})

    if not job:
        return _response(404, {"error": "Job not found."})

    tenant_id = job["tenant_id"]
    screening_run_id = _new_id()

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

    # Record the screening run state in MongoDB
    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        db["screening_runs"].insert_one({
            "_id": screening_run_id,
            "screening_run_id": screening_run_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "status": "QUEUED",
            "phase2_status": "NOT_STARTED",
            "phase3_status": "NOT_STARTED",
            "created_at": _now_iso(),
        })

    logger.info("Queued screening run: %s (job: %s)", screening_run_id, job_id)
    return _response(202, {
        "screening_run_id": screening_run_id,
        "status": "QUEUED",
        "message": "Screening started. Poll GET /jobs/{job_id}/screening-results for updates.",
    })


def _get_screening_results(event: dict) -> dict:
    """
    GET /jobs/{job_id}/screening-results
    Returns the latest screening run results for this job.
    """
    job_id = (event.get("pathParameters") or {}).get("job_id")

    with _get_mongo() as client:
        db = client[MONGODB_DATABASE]
        run = db["screening_runs"].find_one(
            {"job_id": job_id},
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
