"""
CLI entry point for the Phase 3 semantic reranker.

Usage:
    python -m phase3.rerank --job jobs/backend-engineer-001.txt --input outputs/backend-engineer-001-retrieval.json [options]
"""
import argparse
import logging
import sys

from phase3 import config
from phase3.reranker.rerank import run_reranking_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phase3.rerank",
        description="Phase 3 Semantic Reranking: Refines the Phase 2 candidate pool."
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
        help="Path to Phase 2 retrieval output JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        metavar="DIR",
        help="Directory for output JSON files (default: outputs/).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        metavar="K",
        help="Max candidates to output (default: all).",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Voyage Rerank model (default: VOYAGE_RERANK_MODEL).",
    )
    parser.add_argument(
        "--max-document-tokens",
        type=int,
        default=None,
        metavar="CHARS",
        help="Max characters for reconstructed resume document.",
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

    try:
        config.validate()
    except EnvironmentError as exc:
        logging.error("%s", exc)
        sys.exit(1)

    try:
        run_reranking_pipeline(
            job_file=args.job,
            input_json=args.input,
            output_dir=args.output_dir,
            top_k=args.top_k,
            model=args.model,
            max_doc_chars=args.max_document_tokens,
        )
    except Exception as exc:
        logging.error("Reranking failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
