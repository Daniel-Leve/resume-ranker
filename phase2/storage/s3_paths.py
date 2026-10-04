"""
Multi-tenant S3 path utilities.

New S3 path format (SaaS mode):
    tenants/{tenant_id}/jobs/{job_id}/applications/{application_id}/extracted.json
    tenants/{tenant_id}/jobs/{job_id}/applications/{application_id}/original.pdf

Legacy path format (single-tenant CLI prototype):
    incoming/{filename}.pdf
    extracted/{textract-job-id}.json

This module provides parsing utilities that detect which format is in use
and extract the relevant IDs. Functions are pure / deterministic — no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class S3PathContext:
    """
    Structured identity extracted from an S3 key.

    In SaaS mode all four fields are populated.
    In legacy (prototype) mode only source_key is meaningful;
    tenant_id / job_id / application_id are None.
    """
    source_key: str
    tenant_id: Optional[str] = None
    job_id: Optional[str] = None
    application_id: Optional[str] = None

    @property
    def is_multitenant(self) -> bool:
        """True when the key was parsed from the SaaS path format."""
        return bool(self.tenant_id and self.job_id and self.application_id)


# Expected SaaS path (storage format): tenants/{tid}/jobs/{jid}/applications/{aid}/...
_SAAS_PATTERN = re.compile(
    r"^tenants/(?P<tenant_id>[^/]+)/jobs/(?P<job_id>[^/]+)"
    r"/applications/(?P<application_id>[^/]+)/",
    re.IGNORECASE,
)

# Expected SaaS path (upload format to satisfy Phase 1 Lambda): incoming/saas__{tid}__{jid}__{aid}.pdf
_SAAS_INCOMING_PATTERN = re.compile(
    r"^incoming/saas__(?P<tenant_id>[^_]+)__(?P<job_id>[^_]+)__(?P<application_id>[^\.]+)\.pdf",
    re.IGNORECASE,
)


def parse_s3_key(s3_key: str) -> S3PathContext:
    """
    Parse an S3 key into a structured S3PathContext.

    Args:
        s3_key: The full S3 object key (e.g. from a Lambda event or listing).

    Returns:
        S3PathContext with tenant/job/application IDs populated if the
        key matches the SaaS format, or with all IDs as None if legacy.
    """
    match = _SAAS_PATTERN.match(s3_key)
    if match:
        return S3PathContext(
            source_key=s3_key,
            tenant_id=match.group("tenant_id"),
            job_id=match.group("job_id"),
            application_id=match.group("application_id"),
        )
    
    match2 = _SAAS_INCOMING_PATTERN.match(s3_key)
    if match2:
        return S3PathContext(
            source_key=s3_key,
            tenant_id=match2.group("tenant_id"),
            job_id=match2.group("job_id"),
            application_id=match2.group("application_id"),
        )

    # Legacy path - return context with only source_key set
    return S3PathContext(source_key=s3_key)


def build_saas_extraction_key(
    tenant_id: str,
    job_id: str,
    application_id: str,
) -> str:
    """Build the canonical SaaS S3 path for an extracted.json file."""
    return f"tenants/{tenant_id}/jobs/{job_id}/applications/{application_id}/extracted.json"


def build_saas_resume_key(
    tenant_id: str,
    job_id: str,
    application_id: str,
    filename: str = "original.pdf",
) -> str:
    """Build the canonical SaaS S3 path for an uploaded PDF resume.
       (Uses incoming/ prefix to satisfy legacy Phase 1 hardcoded triggers)"""
    return f"incoming/saas__{tenant_id}__{job_id}__{application_id}.pdf"
