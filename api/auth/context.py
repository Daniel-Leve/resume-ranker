"""
Authentication Context Extraction — Block 3.

Extracts and validates the authenticated user's identity from the
API Gateway requestContext populated by a Cognito JWT Authorizer.

Design decisions:
  - The JWT is already verified by API Gateway / Cognito before the Lambda
    is invoked. We only read the pre-verified claims from requestContext.
  - tenant_id is NEVER read from path parameters or request body for
    authorization decisions. It always comes from the verified JWT claims
    or from a trusted MongoDB membership lookup.
  - The `tenant_memberships` MongoDB collection maps:
        { user_sub (Cognito sub), tenant_id, role, created_at }
    This supports future multi-tenant membership (one user → N tenants)
    while still enabling simple single-tenant flows today.

Security contract:
  - extract_auth_context() returns (user_sub, user_email) from the JWT claims.
  - get_user_tenant_membership() looks up which tenants the user belongs to
    and what role they hold (ADMIN | MEMBER).
  - require_tenant_access() enforces that the authenticated user is a member
    of the requested tenant_id with the minimum required role.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from pymongo.collection import Collection

logger = logging.getLogger(__name__)


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthContext:
    """
    Verified identity extracted from Cognito JWT claims.
    Populated from event['requestContext']['authorizer']['claims'].
    """
    user_sub: str       # Cognito subject (immutable, globally unique user ID)
    email: str          # User's email address (used for display / audit)
    username: str       # Cognito username (may differ from email)


@dataclass(frozen=True)
class TenantMembership:
    """One user's membership record in a specific tenant."""
    user_sub: str
    tenant_id: str
    role: str           # "ADMIN" or "MEMBER"


# ─── JWT Claims Extraction ────────────────────────────────────────────────────

def extract_auth_context(event: dict) -> Optional[AuthContext]:
    """
    Extract the authenticated user's identity from the API Gateway event.

    API Gateway with a Cognito User Pool authorizer populates:
        event['requestContext']['authorizer']['claims']
    with the decoded, verified JWT payload before invoking the Lambda.

    Returns None if no verified claims are present (unauthenticated request).
    The caller is responsible for returning a 401 in that case.
    """
    try:
        claims: dict = (
            event.get("requestContext", {})
                 .get("authorizer", {})
                 .get("claims", {})
        )
    except (AttributeError, TypeError):
        return None

    user_sub = claims.get("sub", "").strip()
    email = claims.get("email", "").strip()
    username = claims.get("cognito:username", "").strip()

    if not user_sub:
        return None

    return AuthContext(
        user_sub=user_sub,
        email=email,
        username=username,
    )


# ─── Tenant Membership Lookup ─────────────────────────────────────────────────

def get_user_tenant_memberships(
    memberships_collection: Collection,
    user_sub: str,
) -> List[TenantMembership]:
    """
    Return all tenant memberships for the given Cognito user_sub.

    Queries the `tenant_memberships` MongoDB collection:
        { user_sub, tenant_id, role, created_at }

    Args:
        memberships_collection: The MongoDB `tenant_memberships` collection.
        user_sub:               The Cognito subject claim (JWT `sub`).

    Returns:
        List of TenantMembership dataclasses. Empty list means no tenants.
    """
    docs = memberships_collection.find(
        {"user_sub": user_sub},
        {"tenant_id": 1, "role": 1, "_id": 0},
    )
    return [
        TenantMembership(
            user_sub=user_sub,
            tenant_id=doc["tenant_id"],
            role=doc.get("role", "MEMBER"),
        )
        for doc in docs
    ]


def get_user_tenant_membership(
    memberships_collection: Collection,
    user_sub: str,
    tenant_id: str,
) -> Optional[TenantMembership]:
    """
    Return the specific membership record for (user_sub, tenant_id), or None.

    Use this for single-tenant authorization checks:
        membership = get_user_tenant_membership(col, sub, tenant_id)
        if not membership:
            return _response(403, {"error": "Forbidden"})

    Args:
        memberships_collection: The MongoDB `tenant_memberships` collection.
        user_sub:               The Cognito subject claim.
        tenant_id:              The tenant the caller claims to access.

    Returns:
        TenantMembership if found, None if the user has no access.
    """
    doc = memberships_collection.find_one(
        {"user_sub": user_sub, "tenant_id": tenant_id},
        {"tenant_id": 1, "role": 1, "_id": 0},
    )
    if not doc:
        return None
    return TenantMembership(
        user_sub=user_sub,
        tenant_id=doc["tenant_id"],
        role=doc.get("role", "MEMBER"),
    )


def require_tenant_access(
    memberships_collection: Collection,
    auth: AuthContext,
    tenant_id: str,
    minimum_role: str = "MEMBER",
) -> Optional[TenantMembership]:
    """
    Verify that `auth.user_sub` holds at least `minimum_role` in `tenant_id`.

    Role hierarchy (lowest to highest):
        MEMBER < ADMIN

    Args:
        memberships_collection: MongoDB `tenant_memberships` collection.
        auth:                   The verified AuthContext from extract_auth_context().
        tenant_id:              The tenant being accessed (from URL path).
        minimum_role:           Required role ("MEMBER" or "ADMIN").

    Returns:
        TenantMembership if access is granted, None if denied.
    """
    _ROLE_RANK = {"MEMBER": 0, "ADMIN": 1}

    membership = get_user_tenant_membership(
        memberships_collection, auth.user_sub, tenant_id
    )
    if not membership:
        return None

    actual_rank = _ROLE_RANK.get(membership.role, -1)
    required_rank = _ROLE_RANK.get(minimum_role, 0)

    if actual_rank < required_rank:
        logger.warning(
            "User %s has role %s in tenant %s but %s is required.",
            auth.user_sub, membership.role, tenant_id, minimum_role,
        )
        return None

    return membership
