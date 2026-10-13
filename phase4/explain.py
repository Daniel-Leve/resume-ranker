"""
CLI entry point for Phase 4 Explainability.

Usage:
    python -m phase4.explain --job jobs/backend-engineer-001.txt --input outputs/backend-engineer-001-reranked.json [options]
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from pymongo import MongoClient

from phase4 import config
from phase4.explainer import generate_explanations

logger = logging.getLogger("phase4.explain")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phase4.explain",
        description="Phase 4 Explainability: Grounded, recruiter-friendly ranking explanations."
    )
    parser.add_argument(
        "--job",
        required=True,
        metavar="JOB_FILE",
        help="Path to job description .txt file.",
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="JSON_FILE",
        help="Path to Phase 3 reranked output JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        metavar="DIR",
        help="Directory for output JSON files (default: outputs/).",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        metavar="TENANT_ID",
        help="Optional tenant_id for tenant-scoped chunk retrieval.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    jd_path = Path(args.job)
    if not jd_path.exists():
        logger.error("Job file not found: %s", jd_path)
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input JSON file not found: %s", input_path)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        p3_data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse input JSON: %s", exc)
        sys.exit(1)

    job_id = jd_path.stem

    # Attempt to connect to MongoDB if URI is configured
    mongo_client = None
    collection = None
    if config.MONGODB_URI:
        try:
            import certifi
            mongo_client = MongoClient(
                config.MONGODB_URI,
                serverSelectionTimeoutMS=2000,
                tlsCAFile=certifi.where(),
            )
            mongo_client.admin.command("ping")
            collection = mongo_client[config.MONGODB_DATABASE][config.MONGODB_COLLECTION]
            logger.info("Connected to MongoDB Atlas for chunk retrieval.")
        except Exception as exc:
            logger.warning("Could not connect to MongoDB Atlas (%s). Proceeding with available metadata.", exc)
            collection = None

    try:
        report = generate_explanations(
            phase3_output=p3_data,
            job_description=jd_path,
            collection=collection,
            tenant_id=args.tenant_id,
            job_id=job_id,
        )

        out_file = output_dir / f"{job_id}-explained.json"
        out_file.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info("=" * 55)
        logger.info("Phase 4 Explainability complete for job: %s", job_id)
        logger.info("  Candidates explained: %d", report.candidate_count)
        logger.info("  Saved explanation to: %s", out_file)
        logger.info("=" * 55)

    finally:
        if mongo_client:
            mongo_client.close()


if __name__ == "__main__":
    main()
