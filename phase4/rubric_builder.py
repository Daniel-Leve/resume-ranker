"""
Phase 4a: Rubric Builder and Approval Gate.
Converts a Job Description into a structured 4-8 criteria rubric and enforces human approval.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from phase4 import config
from phase4.llm_client import LLMClient
from phase4.schemas import JobRubric, RubricCriterion

logger = logging.getLogger(__name__)

RUBRIC_SYSTEM_PROMPT = """You are an expert technical recruiter and talent evaluation specialist.
Your task is to analyze the provided Job Description (JD) and produce a rigorous, objective candidate evaluation rubric.

REQUIREMENTS:
1. Extract between 4 and 8 essential criteria that define candidate suitability for this specific role.
2. Categorize each criterion strictly as:
   - "must": Non-negotiable core requirements (e.g. required language, core architecture, critical domain experience).
   - "nice": Preferred qualifications or bonus skills (e.g. secondary tools, nice-to-have certifications).
3. Assign a normalized weight between 0.0 and 1.0 to each criterion such that the sum of all weights equals 1.0. "must" criteria must receive higher weights than "nice" criteria.
4. For each criterion, provide a concise "how_to_verify" guideline specifying what factual, verifiable evidence in a resume satisfies the requirement.
5. Assign a concise ID for each criterion: "c1", "c2", "c3", etc.

OUTPUT FORMAT:
Output strictly a JSON object conforming to this schema:
{
  "criteria": [
    {
      "id": "c1",
      "description": "3+ years production experience with Python and FastAPI or Django",
      "type": "must",
      "weight": 0.25,
      "how_to_verify": "Look for explicit mentions of Python backend frameworks and years of experience or production project responsibilities"
    }
  ]
}
"""


def build_rubric(
    jd_text: str,
    jd_id: str,
    llm_client: LLMClient,
    rubrics_dir: Path = config.RUBRICS_DIR,
    version: str = "v1",
) -> JobRubric:
    """
    Generate an objective, structured rubric from JD text using LLM in JSON mode.
    Saves the rubric as DRAFT to the rubrics directory.
    """
    if not jd_text or not jd_text.strip():
        raise ValueError("Job description text cannot be empty.")
    if not jd_id or not jd_id.strip():
        raise ValueError("jd_id cannot be empty.")

    jd_id = jd_id.strip()
    rubrics_dir = Path(rubrics_dir)
    try:
        rubrics_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create rubrics directory %s: %s", rubrics_dir, exc)

    messages = [
        {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
        {"role": "user", "content": f"JOB DESCRIPTION (ID: {jd_id}):\n\n{jd_text.strip()}"},
    ]

    logger.info("Generating rubric for job %s using %s...", jd_id, llm_client.__class__.__name__)
    raw_rubric_schema, response = llm_client.complete_structured(
        messages=messages,
        schema_class=JobRubricWrapper,
        temperature=0.0,
    )

    rubric = JobRubric(
        jd_id=jd_id,
        version=version,
        status="DRAFT",
        created_at=datetime.now(timezone.utc).isoformat(),
        criteria=raw_rubric_schema.criteria,
    )

    # Save draft rubric to file (best-effort local cache)
    try:
        out_file = rubrics_dir / f"{jd_id}_rubric_{version}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(rubric.model_dump(), f, indent=2)
        logger.info("Saved DRAFT rubric with %d criteria to %s", len(rubric.criteria), out_file)
    except OSError as exc:
        logger.warning("Could not save rubric file %s: %s", rubrics_dir, exc)
    return rubric


class JobRubricWrapper(JobRubric):
    """Wrapper to support raw LLM output which only includes 'criteria' list."""
    jd_id: str = "pending"
    criteria: List[RubricCriterion]


def get_rubric(
    jd_id: str,
    rubrics_dir: Path = config.RUBRICS_DIR,
    version: str = "v1",
) -> Optional[JobRubric]:
    """Load existing rubric from disk."""
    rubrics_dir = Path(rubrics_dir)
    rubric_file = rubrics_dir / f"{jd_id.strip()}_rubric_{version}.json"
    if not rubric_file.exists():
        return None
    with open(rubric_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JobRubric.model_validate(data)


def get_next_rubric_version(jd_id: str, rubrics_dir: Path = config.RUBRICS_DIR) -> str:
    """Determine next version string (v1, v2, v3, ...) based on existing rubrics."""
    rubrics_dir = Path(rubrics_dir)
    pattern = f"{jd_id.strip()}_rubric_v*.json"
    existing = list(rubrics_dir.glob(pattern))
    if not existing:
        return "v1"
    versions = []
    for p in existing:
        stem = p.stem  # e.g. "job-1_rubric_v2"
        parts = stem.split("_rubric_v")
        if len(parts) == 2 and parts[1].isdigit():
            versions.append(int(parts[1]))
    if not versions:
        return "v1"
    return f"v{max(versions) + 1}"


def approve_rubric(
    jd_id: str,
    approved_by: Optional[str] = "recruiter",
    custom_criteria: Optional[List[Dict[str, Any]]] = None,
    rubrics_dir: Path = config.RUBRICS_DIR,
    version: str = "v1",
) -> JobRubric:
    """
    Approve a rubric, transitioning status from DRAFT to APPROVED.
    Optionally allows human tweaking of criteria and weights prior to locking.
    Approved rubrics are strictly immutable — modifications require a new version.
    """
    rubrics_dir = Path(rubrics_dir)
    rubric_file = rubrics_dir / f"{jd_id.strip()}_rubric_{version}.json"
    if not rubric_file.exists():
        raise FileNotFoundError(f"Rubric file not found at {rubric_file}. Build the rubric first.")

    with open(rubric_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Immutability enforcement: cannot modify criteria of an already approved rubric
    if data.get("status") == "APPROVED":
        if custom_criteria and custom_criteria != data.get("criteria"):
            raise ValueError(
                f"Rubric for {jd_id} version {version} is already APPROVED and immutable. "
                f"Build a new rubric version to make modifications."
            )
        return JobRubric.model_validate(data)

    if custom_criteria:
        data["criteria"] = custom_criteria

    rubric = JobRubric.model_validate(data)
    rubric.status = "APPROVED"
    rubric.approved_at = datetime.now(timezone.utc).isoformat()
    rubric.approved_by = approved_by or "recruiter"

    try:
        with open(rubric_file, "w", encoding="utf-8") as f:
            json.dump(rubric.model_dump(), f, indent=2)
    except OSError as exc:
        logger.warning("Could not write approved rubric file %s: %s", rubric_file, exc)

    logger.info("Rubric for %s (%s) has been APPROVED by %s.", jd_id, version, rubric.approved_by)
    return rubric
