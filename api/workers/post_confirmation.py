"""
Cognito Post-Confirmation Lambda Trigger — Block 3.

Triggered by Cognito after a new user confirms their account
(either via email OTP or admin confirmation).

Responsibility:
  - Read the confirmed user's sub, email, username from the Cognito event.
  - Check if the user already has a membership record (idempotent).
  - Do NOT automatically create a tenant — that requires the user to
    explicitly call POST /tenants.
  - Instead, log the new user and leave the membership table empty.
    The user will create (or be invited to) a tenant separately.

Why no automatic tenant creation here?
  If a company has multiple HR staff, they should all belong to the SAME
  tenant, not each get their own isolated tenant. So tenant creation is a
  deliberate action performed after registration, not a side effect of it.

Event payload (from Cognito PostConfirmation trigger):
    {
        "version": "1",
        "triggerSource": "PostConfirmation_ConfirmSignUp",
        "region": "ap-south-1",
        "userPoolId": "ap-south-1_XXXXXXXXX",
        "userName": "user@example.com",
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-...",
                "email": "user@example.com",
                "email_verified": "true",
                ...
            }
        },
        "response": {}
    }
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import certifi
from pymongo import MongoClient

from api.auth.secrets import get_mongodb_uri

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "resume_screening")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lambda_handler(event: dict, context: object) -> dict:
    """
    Cognito PostConfirmation trigger handler.

    Logs the new user. Does NOT automatically create a tenant — the user
    must explicitly POST /tenants after registration to establish their company.

    Always returns the original event unchanged (required by Cognito triggers).
    """
    trigger_source = event.get("triggerSource", "")
    user_attributes = event.get("request", {}).get("userAttributes", {})

    user_sub = user_attributes.get("sub", "").strip()
    email = user_attributes.get("email", "").strip()
    username = event.get("userName", "").strip()

    logger.info(
        "PostConfirmation triggered: source=%s user_sub=%s",
        trigger_source, user_sub,
    )

    if not user_sub:
        logger.error("PostConfirmation: missing sub in userAttributes — skipping.")
        return event

    mongo_client = MongoClient(
        get_mongodb_uri(),
        serverSelectionTimeoutMS=10_000,
        tlsCAFile=certifi.where(),
    )
    try:
        db = mongo_client[MONGODB_DATABASE]

        # Upsert a user profile record (idempotent)
        db["users"].update_one(
            {"_id": user_sub},
            {
                "$setOnInsert": {
                    "_id": user_sub,
                    "user_sub": user_sub,
                    "email": email,
                    "username": username,
                    "created_at": _now_iso(),
                }
            },
            upsert=True,
        )
        logger.info("User profile created/verified for sub=%s", user_sub)

    except Exception as exc:
        # Never raise from a Cognito trigger — it would block sign-up
        logger.error(
            "PostConfirmation: failed to write user record for sub=%s: %s",
            user_sub, exc, exc_info=True,
        )
    finally:
        mongo_client.close()

    # Must return the event unchanged for Cognito to complete the flow
    return event
