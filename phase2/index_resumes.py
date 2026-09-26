"""
CLI entry point for the Phase 2 resume indexer.

Usage:
    python -m phase2.index_resumes [options]

Options:
    --dry-run          Report what would be indexed; make no writes.
    --candidate ID     Process only the named candidate_id.
    --force            Re-index even if content hash is unchanged.
    --bucket NAME      Override S3_BUCKET_NAME env var.
    --log-level LEVEL  DEBUG | INFO | WARNING | ERROR  (default: INFO)

Examples:
    # Index all resumes from Phase 1:
    python -m phase2.index_resumes

    # Dry run — see what would be indexed:
    python -m phase2.index_resumes --dry-run

    # Force re-index a single candidate:
    python -m phase2.index_resumes --candidate john-doe --force
"""
from phase2.indexer.index_resumes import main

if __name__ == "__main__":
    main()
