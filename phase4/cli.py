"""
Phase 4 Command Line Interface (CLI).
Provides complete terminal workflows: build-rubric, approve-rubric, evaluate,
reconcile, report, status, and review-queue.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from phase4 import config
from phase4.daily_budget import DailyBudget
from phase4.generators import generate_hr_report
from phase4.llm_client import GroqClient
from phase4.orchestrator import Phase4Orchestrator
from phase4.review_queue import GLOBAL_REVIEW_QUEUE
from phase4.rubric_builder import approve_rubric, build_rubric, get_rubric

logger = logging.getLogger("phase4.cli")


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def cmd_build_rubric(args: argparse.Namespace) -> None:
    jd_path = Path(args.jd)
    if not jd_path.exists():
        print(f"Error: Job description file not found at {jd_path}", file=sys.stderr)
        sys.exit(1)

    jd_text = jd_path.read_text(encoding="utf-8")
    jd_id = args.jd_id or jd_path.stem

    client = GroqClient()
    rubric = build_rubric(
        jd_text=jd_text,
        jd_id=jd_id,
        llm_client=client,
        version=args.version,
    )

    print("\n" + "=" * 60)
    print(f"✅ DRAFT RUBRIC CREATED for Job: {rubric.jd_id} ({rubric.version})")
    print("=" * 60)
    for c in rubric.criteria:
        print(f"[{c.id.upper()}] ({c.type.upper()}, weight={c.weight:.2f})")
        print(f"  Requirement: {c.description}")
        print(f"  Verification: {c.how_to_verify}")
    print("=" * 60)
    print("⚠️  Status: DRAFT. Run 'approve-rubric' before resumes can be evaluated.\n")


def cmd_approve_rubric(args: argparse.Namespace) -> None:
    try:
        rubric = approve_rubric(
            jd_id=args.jd_id,
            approved_by=args.approved_by,
            version=args.version,
        )
        print("\n" + "=" * 60)
        print(f"✅ RUBRIC APPROVED for Job: {rubric.jd_id} ({rubric.version})")
        print(f"Approved by: {rubric.approved_by} at {rubric.approved_at}")
        print(f"Total Criteria: {len(rubric.criteria)}")
        print("=" * 60)
        print("System is now ready to evaluate resumes for this job.\n")
    except Exception as exc:
        print(f"Error approving rubric: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_evaluate(args: argparse.Namespace) -> None:
    jd_id = args.jd_id
    if not jd_id:
        print("Error: --jd-id is required.", file=sys.stderr)
        sys.exit(1)

    resumes_path = Path(args.resumes)
    if not resumes_path.exists():
        print(f"Error: Resumes path {resumes_path} not found.", file=sys.stderr)
        sys.exit(1)

    # Load resumes: either a single JSON file with list of items, or a directory of text/json files
    resumes_data = []
    if resumes_path.is_file():
        content = resumes_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, list):
            resumes_data = data
        elif isinstance(data, dict):
            if "resumes" in data:
                resumes_data = data["resumes"]
            else:
                resumes_data = [data]
    elif resumes_path.is_dir():
        for f in resumes_path.glob("*.json"):
            try:
                resumes_data.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        for f in resumes_path.glob("*.txt"):
            resumes_data.append({"resume_id": f.stem, "raw_text": f.read_text(encoding="utf-8")})

    phase3_data = None
    if args.rerank:
        p3_path = Path(args.rerank)
        if p3_path.exists():
            phase3_data = json.loads(p3_path.read_text(encoding="utf-8"))

    orchestrator = Phase4Orchestrator()
    results = orchestrator.evaluate_batch(
        jd_id=jd_id,
        resumes=resumes_data,
        phase3_results=phase3_data,
        tenant_id=args.tenant_id,
    )

    print("\n" + "=" * 60)
    print(f"🎯 BATCH EVALUATION COMPLETE: {results['job_id']}")
    print("=" * 60)
    print(f"Status:                      {results['status']}")
    print(f"Total Resumes Submitted:     {results['total_submitted']}")
    print(f"Evaluated (Active Run):      {results['evaluated_count']}")
    print(f"Skipped via Resumable Cache: {results['cache_hits']}")
    print(f"Auto-Decisions:              {results['auto_decisions']}")
    print(f"Human Review Queue:          {results['human_review_queue']}")
    print(f"Pending (Budget Cap Pause):  {results['pending_count']}")
    print(f"Estimated Days Remaining:    {results['estimated_days_remaining']} day(s)")
    print(f"Quote Verification Metric:   {results['verification_metric']}")
    print("=" * 60)
    print(f"HR Reports:                  {config.REPORTS_DIR / jd_id}")
    print(f"Candidate Feedbacks:         {config.FEEDBACK_DIR}\n")


def cmd_status(args: argparse.Namespace) -> None:
    jd_id = args.jd_id
    budget = DailyBudget()
    status_data = budget.get_budget_status()

    # Query review queue items
    queue = GLOBAL_REVIEW_QUEUE.list_items(job_id=jd_id, status="NEEDS_REVIEW")

    # Count cached evaluations
    cache_count = len(list(config.CACHE_DIR.glob("*.json")))

    print("\n" + "=" * 60)
    print(f"📊 PHASE 4 SYSTEM & BUDGET DASHBOARD: {jd_id or 'ALL JOBS'}")
    print("=" * 60)
    print(f"Today (UTC):                 {status_data['date']}")
    print(f"Tokens Used Today:           {status_data['tokens_used_today']:,} / {status_data['daily_token_limit']:,} ({status_data['tokens_used_pct']}%)")
    print(f"Tokens Remaining:            {status_data['tokens_remaining']:,}")
    print(f"Requests Used Today:         {status_data['requests_used_today']} / {status_data['daily_request_limit']}")
    print(f"Stop Threshold:              {status_data['stop_threshold_tokens']:,} tokens ({status_data['stop_threshold_pct']}%)")
    print(f"Budget Exceeded:             {'⚠️ YES (Graceful Pause Active)' if status_data['is_budget_exceeded'] else '✅ NO (Ready)'}")
    print("-" * 60)
    print(f"Cached Resume Evaluations:   {cache_count}")
    print(f"Human Review Queue:          {len(queue)} pending candidate(s)")
    print("=" * 60 + "\n")


def cmd_review_queue(args: argparse.Namespace) -> None:
    action = args.queue_action

    if action == "list":
        items = GLOBAL_REVIEW_QUEUE.list_items(job_id=args.jd_id, status=args.status)
        print("\n" + "=" * 60)
        print(f"📋 HUMAN REVIEW QUEUE ({len(items)} items)")
        print("=" * 60)
        for item in items:
            score_str = f"score={item.weighted_score:.2f}"
            rank_str = f"rank=#{item.rerank_rank}" if item.rerank_rank else "unranked"
            print(f"- ID: {item.resume_id} (Job: {item.job_id}, {rank_str}, {score_str})")
            print(f"  Status: {item.status}")
            print(f"  Flags:  {', '.join(item.flag_reasons)}")
        print("=" * 60 + "\n")

    elif action == "show":
        item = GLOBAL_REVIEW_QUEUE.get_item(args.resume_id)
        if not item:
            print(f"Item {args.resume_id} not found in review queue.", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(item.model_dump(), indent=2))

    elif action == "resolve":
        if not args.decision:
            print("Error: --decision [promote|confirm_reject|fix_rubric] is required.", file=sys.stderr)
            sys.exit(1)
        res = GLOBAL_REVIEW_QUEUE.resolve(
            resume_id=args.resume_id,
            action=args.decision,
            notes=args.notes,
            resolved_by=args.resolved_by or "recruiter",
        )
        print(f"\n✅ Resolved item {res.resume_id} with status {res.status}. Override recorded in labeled history.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phase4.cli",
        description="Phase 4: Faithful Explainability Layer CLI",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build-rubric
    p_build = subparsers.add_parser("build-rubric", help="Extract 4-8 criteria rubric from JD text")
    p_build.add_argument("--jd", required=True, help="Path to JD text file")
    p_build.add_argument("--jd-id", default=None, help="Job identifier")
    p_build.add_argument("--version", default="v1", help="Rubric version")

    # approve-rubric
    p_app = subparsers.add_parser("approve-rubric", help="Lock rubric into APPROVED status")
    p_app.add_argument("--jd-id", required=True, help="Job identifier")
    p_app.add_argument("--version", default="v1", help="Rubric version")
    p_app.add_argument("--approved-by", default="recruiter", help="Name/email of approving recruiter")

    # evaluate
    p_eval = subparsers.add_parser("evaluate", help="Run resumable blind evaluation with budget controls")
    p_eval.add_argument("--jd-id", required=True, help="Job identifier")
    p_eval.add_argument("--resumes", required=True, help="Path to resumes JSON file or directory")
    p_eval.add_argument("--rerank", default=None, help="Path to Phase 3 rerank output JSON")
    p_eval.add_argument("--tenant-id", default=None, help="Tenant identifier")

    # status
    p_stat = subparsers.add_parser("status", help="Show system, queue, and daily budget dashboard")
    p_stat.add_argument("--jd-id", default=None, help="Optional job identifier filter")

    # review-queue
    p_rev = subparsers.add_parser("review-queue", help="Manage human review queue and labeled overrides")
    p_rev.add_argument("queue_action", choices=["list", "show", "resolve"])
    p_rev.add_argument("--jd-id", default=None, help="Job identifier filter")
    p_rev.add_argument("--status", default="NEEDS_REVIEW", help="Queue status filter")
    p_rev.add_argument("--resume-id", default=None, help="Target resume ID")
    p_rev.add_argument("--decision", choices=["promote", "confirm_reject", "fix_rubric"])
    p_rev.add_argument("--notes", default=None, help="Override rationale")
    p_rev.add_argument("--resolved-by", default="recruiter", help="Recruiter identifier")

    args = parser.parse_args()
    _setup_logging(args.log_level)

    if args.command == "build-rubric":
        cmd_build_rubric(args)
    elif args.command == "approve-rubric":
        cmd_approve_rubric(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "review-queue":
        cmd_review_queue(args)


if __name__ == "__main__":
    main()
