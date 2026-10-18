"""
Phase 4e: Output Generators.
Generates recruiter-facing HR Reports for shortlisted candidates and
constructive, candidate-facing feedback for rejected candidates.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase4 import config
from phase4.schemas import (
    CandidateFeedback,
    HRReport,
    JobRubric,
    ReconciliationDecision,
    ResumeEvaluation,
)

logger = logging.getLogger(__name__)


def generate_hr_report(
    candidate_id: str,
    job_id: str,
    evaluation: ResumeEvaluation,
    rubric: JobRubric,
    reconciliation: Optional[ReconciliationDecision] = None,
    candidate_name: Optional[str] = None,
    application_id: Optional[str] = None,
    rerank_rank: Optional[int] = None,
    rerank_score: Optional[float] = None,
    reports_dir: Path = config.REPORTS_DIR,
) -> HRReport:
    """
    Generate structured HR shortlist report with match matrix, strengths, gaps, risks,
    and 3-5 targeted interview questions probing unevidenced or partial criteria.
    """
    eval_by_id = {e.criterion_id: e for e in evaluation.evaluations}

    match_matrix: List[Dict[str, Any]] = []
    strengths: List[str] = []
    gaps: List[str] = []
    risks: List[str] = []
    interview_questions: List[str] = []

    for crit in rubric.criteria:
        e = eval_by_id.get(crit.id)
        status = e.status if e else "not_evidenced"
        quotes = [ev.quote for ev in e.evidence] if e else []
        sections = [ev.section for ev in e.evidence] if e else []

        match_matrix.append({
            "criterion_id": crit.id,
            "description": crit.description,
            "type": crit.type,
            "weight": crit.weight,
            "status": status,
            "quotes": quotes,
            "sections": sections,
        })

        if status == "met":
            quote_snip = f' (e.g. "{quotes[0][:80]}...")' if quotes else ""
            strengths.append(f"[{crit.id.upper()}] {crit.description}{quote_snip}")
        elif status == "partial":
            gaps.append(f"[{crit.id.upper()}] {crit.description} - partially evidenced")
            interview_questions.append(
                f"Can you walk us through your hands-on experience with '{crit.description}'? Specifically, what was the scale and production impact?"
            )
        else:
            gaps.append(f"[{crit.id.upper()}] {crit.description} - not evidenced in resume")
            if crit.type == "must":
                risks.append(f"Core Must-Have Not Evidenced: {crit.description}")
            interview_questions.append(
                f"Our team heavily relies on '{crit.description}'. Can you describe any previous projects or coursework where you applied this skill?"
            )

    # Check reconciliation notes for risks
    if reconciliation and reconciliation.flag_notes:
        for note in reconciliation.flag_notes:
            if "high_similarity_weak_evidence" in note:
                risks.append("High semantic similarity from initial search, but weak direct textual evidence for core must-haves.")
            elif "poor_parse_quality" in note:
                risks.append("Resume parsing was flagged as poor quality or truncated. Some skills may have been missed.")

    # Bound interview questions between 3 and 5
    if len(interview_questions) < 3:
        interview_questions.append("Tell us about an architectural decision or trade-off you had to make in a recent technical project.")
    if len(interview_questions) < 3:
        interview_questions.append("How do you typically approach automated testing, debugging, and deployment in production?")
    interview_questions = interview_questions[:5]

    report = HRReport(
        candidate_id=candidate_id,
        application_id=application_id,
        candidate_name=candidate_name,
        job_id=job_id,
        rerank_rank=rerank_rank,
        rerank_score=rerank_score,
        match_matrix=match_matrix,
        strengths=strengths,
        gaps=gaps,
        risks=risks,
        interview_questions=interview_questions,
    )

    # Save to disk (best-effort local storage)
    try:
        job_report_dir = Path(reports_dir) / job_id
        job_report_dir.mkdir(parents=True, exist_ok=True)

        json_path = job_report_dir / f"hr_report_{candidate_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2)

        md_path = job_report_dir / f"hr_report_{candidate_id}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(_format_hr_report_markdown(report))

        logger.info("Saved HR report for %s to %s", candidate_id, md_path)
    except OSError as exc:
        logger.warning("Could not save HR report to disk: %s", exc)
    return report


def _format_hr_report_markdown(report: HRReport) -> str:
    lines = [
        f"# HR Shortlist Candidate Report: {report.candidate_name or report.candidate_id}",
        f"**Job ID:** `{report.job_id}` | **Candidate ID:** `{report.candidate_id}`",
    ]
    if report.rerank_rank:
        score_str = f" (Score: {report.rerank_score:.3f})" if report.rerank_score is not None else ""
        lines.append(f"**Final Rerank Rank:** #{report.rerank_rank}{score_str}")
    lines.append("")

    lines.append("## Match Matrix")
    lines.append("| ID | Criterion | Type | Status | Evidence Quotes |")
    lines.append("|---|---|---|---|---|")
    for m in report.match_matrix:
        quote_str = "<br/>".join(f'"{q}"' for q in m["quotes"][:2]) if m["quotes"] else "*None*"
        badge = "✅ Met" if m["status"] == "met" else ("⚠️ Partial" if m["status"] == "partial" else "❌ Not Evidenced")
        lines.append(f"| {m['criterion_id'].upper()} | {m['description']} | {m['type'].upper()} | {badge} | {quote_str} |")
    lines.append("")

    lines.append("## Top Strengths")
    for s in (report.strengths or ["*No specific strengths evidenced*"]):
        lines.append(f"- {s}")
    lines.append("")

    lines.append("## Evidence Gaps")
    for g in (report.gaps or ["*No significant evidence gaps*"]):
        lines.append(f"- {g}")
    lines.append("")

    if report.risks:
        lines.append("## Risks & Considerations")
        for r in report.risks:
            lines.append(f"- ⚠️ {r}")
        lines.append("")

    lines.append("## Suggested Interview Questions")
    for i, q in enumerate(report.interview_questions, 1):
        lines.append(f"{i}. {q}")
    lines.append("")

    return "\n".join(lines)


def generate_candidate_feedback(
    resume_id: str,
    job_id: str,
    evaluation: ResumeEvaluation,
    rubric: JobRubric,
    feedback_dir: Path = config.FEEDBACK_DIR,
) -> CandidateFeedback:
    """
    Generate constructive candidate-facing feedback for rejected applicants.
    Tied strictly to must-have criteria gaps.
    ZERO exposure of scores, ranks, percentiles, or other candidates.
    """
    eval_by_id = {e.criterion_id: e for e in evaluation.evaluations}

    # Find what the resume did show
    met_items = [
        crit.description for crit in rubric.criteria
        if eval_by_id.get(crit.id) and eval_by_id[crit.id].status == "met"
    ]
    if met_items:
        what_resume_showed = f"Your resume clearly demonstrated solid foundational strengths in {met_items[0]}."
    else:
        what_resume_showed = "Your resume highlights commendable educational background and foundational technical skills."

    # Must-have gaps only
    must_gaps: List[str] = []
    for crit in rubric.criteria:
        if crit.type == "must":
            e = eval_by_id.get(crit.id)
            if not e or e.status == "not_evidenced":
                must_gaps.append(f"Direct experience with {crit.description}")
            elif e.status == "partial":
                must_gaps.append(f"Demonstrated production depth with {crit.description}")

    if not must_gaps:
        # Fallback to nice gaps if candidate had all must-haves but was in a high-density candidate pool
        for crit in rubric.criteria:
            if crit.type == "nice":
                must_gaps.append(f"Additional experience with {crit.description}")
            if len(must_gaps) >= 2:
                break

    # Bound to 2-4 gaps
    selected_gaps = must_gaps[:3] if must_gaps else ["Specialized technical experience directly aligned with this role"]

    actionable_suggestion = (
        "When tailoring your resume for future opportunities, consider adding bullet points detailing "
        "the architecture, specific tools used, and measurable business outcomes for your most impactful projects."
    )

    feedback = CandidateFeedback(
        resume_id=resume_id,
        job_id=job_id,
        what_resume_showed=what_resume_showed,
        gaps=selected_gaps,
        actionable_suggestion=actionable_suggestion,
    )

    # Save to disk: feedback/<resume_id>.md (best-effort local storage)
    try:
        feedback_dir = Path(feedback_dir)
        feedback_dir.mkdir(parents=True, exist_ok=True)
        out_file = feedback_dir / f"{resume_id}.md"

        md_content = f"""# Application Feedback

Thank you for taking the time to apply for role `{job_id}`.

{feedback.what_resume_showed}

### Areas for Enhancement
For this specific position, the technical review looked for explicit evidence in the following key areas:
{chr(10).join(f"- {g}" for g in feedback.gaps)}

### Recommendation
{feedback.actionable_suggestion}

We wish you the very best in your career journey and future applications.
"""
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info("Saved candidate feedback for %s to %s", resume_id, out_file)
    except OSError as exc:
        logger.warning("Could not save candidate feedback to disk: %s", exc)

    return feedback
