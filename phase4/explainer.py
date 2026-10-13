"""
Phase 4 Explainer Orchestrator.
Combines Phase 3 ranking results, Phase 2 provenance, and Job Description
to generate evidence-grounded candidate ranking explanations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pymongo.collection import Collection

from phase4 import config
from phase4.models import (
    CandidateExplanation,
    JobRequirement,
    Phase4Report,
)
from phase4.parser import parse_job_requirements
from phase4.provider import BaseExplanationProvider, DeterministicExplanationProvider

logger = logging.getLogger(__name__)


def fetch_candidate_chunks_from_db(
    collection: Collection,
    candidate_id: str,
    tenant_id: Optional[str] = None,
    job_id: Optional[str] = None,
    application_id: Optional[str] = None,
    resume_version: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve chunks for a candidate strictly scoped by tenant and job context.
    Prevents cross-tenant or cross-job data leakage.
    """
    query: Dict[str, Any] = {"candidate_id": candidate_id}

    if tenant_id and tenant_id.strip():
        query["tenant_id"] = tenant_id.strip()
    if job_id and job_id.strip():
        query["job_id"] = job_id.strip()
    if application_id and application_id.strip():
        query["application_id"] = application_id.strip()
    if resume_version is not None:
        query["resume_version"] = resume_version

    try:
        cursor = collection.find(
            query,
            {
                "_id": 0,
                "chunk_id": 1,
                "candidate_id": 1,
                "tenant_id": 1,
                "job_id": 1,
                "section": 1,
                "text": 1,
                "chunk_index": 1,
            },
        ).sort("chunk_index", 1)
        return list(cursor)
    except Exception as exc:
        logger.warning(
            "Failed to retrieve chunks from MongoDB for candidate %s (%s). Proceeding with empty chunks.",
            candidate_id,
            exc,
        )
        return []


def generate_explanations(
    phase3_output: Union[Dict[str, Any], Any],
    job_description: Union[str, Path],
    collection: Optional[Collection] = None,
    tenant_id: Optional[str] = None,
    job_id: Optional[str] = None,
    provider: Optional[BaseExplanationProvider] = None,
    candidate_chunks_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    screening_run_id: Optional[str] = None,
) -> Phase4Report:
    """
    Generate Phase 4 explanations for candidates ranked in Phase 3.

    Args:
        phase3_output: Phase3 output dict or dataclass (must contain 'candidates' list).
        job_description: Job description raw text or Path to job description file.
        collection: Optional MongoDB collection for fetching candidate chunks.
        tenant_id: Tenant context for tenant-isolated querying.
        job_id: Job context.
        provider: Custom or default explanation provider. Defaults to DeterministicExplanationProvider.
        candidate_chunks_map: Optional pre-fetched map of candidate_id -> list of chunks.
        screening_run_id: Optional screening run identifier for provenance.

    Returns:
        Phase4Report containing all candidate explanations while preserving original ranking.
    """
    # ── Normalize Job Description ──────────────────────────────────────────────
    if isinstance(job_description, Path):
        jd_text = job_description.read_text(encoding="utf-8").strip()
    elif isinstance(job_description, str):
        p = Path(job_description)
        if p.exists() and p.is_file():
            jd_text = p.read_text(encoding="utf-8").strip()
        else:
            jd_text = job_description.strip()
    else:
        jd_text = str(job_description).strip()

    # Parse requirements
    requirements = parse_job_requirements(jd_text)

    # ── Normalize Phase 3 Data ─────────────────────────────────────────────────
    if hasattr(phase3_output, "to_dict"):
        p3_dict = phase3_output.to_dict()
    elif isinstance(phase3_output, dict):
        p3_dict = phase3_output
    else:
        raise TypeError(f"Unsupported phase3_output type: {type(phase3_output)}")

    resolved_job_id = job_id or p3_dict.get("job_id", "unknown")
    candidates_list: List[Dict[str, Any]] = p3_dict.get("candidates", [])

    used_provider = provider or DeterministicExplanationProvider()
    generator_type = "deterministic" if isinstance(used_provider, DeterministicExplanationProvider) else "custom"

    explanations: List[CandidateExplanation] = []

    # ── Process Candidates in Exact Phase 3 Order ──────────────────────────────
    for idx, cand in enumerate(candidates_list):
        if hasattr(cand, "to_dict"):
            cand_dict = cand.to_dict()
        else:
            cand_dict = dict(cand)

        cid = cand_dict.get("candidate_id", f"candidate_{idx+1}")
        app_id = cand_dict.get("application_id")
        resume_version = cand_dict.get("resume_version")

        # Resolve candidate chunks
        chunks: List[Dict[str, Any]] = []
        if candidate_chunks_map and cid in candidate_chunks_map:
            chunks = candidate_chunks_map[cid]
        elif collection is not None:
            chunks = fetch_candidate_chunks_from_db(
                collection=collection,
                candidate_id=cid,
                tenant_id=tenant_id,
                job_id=resolved_job_id,
                application_id=app_id,
                resume_version=resume_version,
            )

        # Generate explanation
        explanation = used_provider.generate_candidate_explanation(
            candidate_data=cand_dict,
            candidate_chunks=chunks,
            requirements=requirements,
        )

        # Guard: strictly preserve original Phase 3 rank and order
        expected_rank = cand_dict.get("rerank_rank", idx + 1)
        explanation.rerank_rank = expected_rank

        explanations.append(explanation)

    report = Phase4Report(
        job_id=resolved_job_id,
        tenant_id=tenant_id,
        screening_run_id=screening_run_id,
        explanation_version=config.EXPLANATION_VERSION,
        generator_type=generator_type,
        candidate_count=len(explanations),
        candidates=explanations,
    )

    return report


def enrich_screening_candidates_with_explanations(
    candidates: List[Dict[str, Any]],
    job_description: str,
    collection: Optional[Collection] = None,
    tenant_id: Optional[str] = None,
    job_id: Optional[str] = None,
    provider: Optional[BaseExplanationProvider] = None,
) -> List[Dict[str, Any]]:
    """
    Enrich a list of candidate dictionaries in-place with an 'explanation' field.
    Preserves all existing candidate keys and original Phase 3 ranks.
    """
    if not candidates:
        return []

    report = generate_explanations(
        phase3_output={"job_id": job_id, "candidates": candidates},
        job_description=job_description,
        collection=collection,
        tenant_id=tenant_id,
        job_id=job_id,
        provider=provider,
    )

    explanation_by_cand_id = {c.candidate_id: c.to_dict() for c in report.candidates}

    enriched = []
    for c in candidates:
        cand_copy = dict(c)
        cid = cand_copy.get("candidate_id")
        if cid and cid in explanation_by_cand_id:
            cand_copy["explanation"] = explanation_by_cand_id[cid]
        enriched.append(cand_copy)

    return enriched
