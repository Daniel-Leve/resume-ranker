"""
Unit tests for phase2.storage.s3_paths
"""
from __future__ import annotations

import pytest

from phase2.storage.s3_paths import (
    S3PathContext,
    build_saas_extraction_key,
    build_saas_resume_key,
    parse_s3_key,
)


class TestParseS3Key:
    def test_saas_path_extracted(self):
        key = "tenants/acme/jobs/job-001/applications/app-xyz/extracted.json"
        ctx = parse_s3_key(key)
        assert ctx.tenant_id == "acme"
        assert ctx.job_id == "job-001"
        assert ctx.application_id == "app-xyz"
        assert ctx.source_key == key
        assert ctx.is_multitenant is True

    def test_saas_path_original_pdf(self):
        key = "tenants/tenant-123/jobs/senior-engineer/applications/app-456/original.pdf"
        ctx = parse_s3_key(key)
        assert ctx.tenant_id == "tenant-123"
        assert ctx.job_id == "senior-engineer"
        assert ctx.application_id == "app-456"
        assert ctx.is_multitenant is True

    def test_legacy_extracted_path(self):
        key = "extracted/18e12c6530ee3a69b386ecbaa37b8b4e.json"
        ctx = parse_s3_key(key)
        assert ctx.tenant_id is None
        assert ctx.job_id is None
        assert ctx.application_id is None
        assert ctx.source_key == key
        assert ctx.is_multitenant is False

    def test_legacy_incoming_path(self):
        key = "incoming/john-doe.pdf"
        ctx = parse_s3_key(key)
        assert ctx.is_multitenant is False

    def test_partial_saas_path_is_legacy(self):
        # Missing the /applications/ segment
        key = "tenants/acme/jobs/job-001/extracted.json"
        ctx = parse_s3_key(key)
        assert ctx.is_multitenant is False

    def test_empty_string(self):
        ctx = parse_s3_key("")
        assert ctx.is_multitenant is False
        assert ctx.source_key == ""

    def test_case_insensitive_match(self):
        key = "TENANTS/acme/JOBS/job-001/APPLICATIONS/app-xyz/extracted.json"
        ctx = parse_s3_key(key)
        assert ctx.is_multitenant is True
        assert ctx.tenant_id == "acme"


class TestBuildSaaSKeys:
    def test_extraction_key(self):
        key = build_saas_extraction_key("acme", "job-001", "app-xyz")
        assert key == "tenants/acme/jobs/job-001/applications/app-xyz/extracted.json"

    def test_resume_key_default_filename(self):
        key = build_saas_resume_key("acme", "job-001", "app-xyz")
        assert key == "tenants/acme/jobs/job-001/applications/app-xyz/original.pdf"

    def test_resume_key_custom_filename(self):
        key = build_saas_resume_key("acme", "job-001", "app-xyz", "john-doe-v2.pdf")
        assert key == "tenants/acme/jobs/job-001/applications/app-xyz/john-doe-v2.pdf"

    def test_roundtrip(self):
        """Built key must be parseable back to the same context."""
        key = build_saas_extraction_key("bigcorp", "backend-001", "app-99")
        ctx = parse_s3_key(key)
        assert ctx.tenant_id == "bigcorp"
        assert ctx.job_id == "backend-001"
        assert ctx.application_id == "app-99"
