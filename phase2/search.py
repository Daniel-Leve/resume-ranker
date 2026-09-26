"""
CLI entry point for the Phase 2 hybrid search.

Usage:
    python -m phase2.search --job JOB_FILE [options]

Required:
    --job FILE         Path to job description .txt file.

Options:
    --top-k K          Max unique candidates to return (default: FINAL_TOP_K).
    --output-dir DIR   Output directory (default: outputs/).
    --lexical-top-k K  BM25 chunk retrieval depth (default: LEXICAL_TOP_K).
    --vector-top-k K   Vector search depth (default: VECTOR_TOP_K).
    --log-level LEVEL  DEBUG | INFO | WARNING | ERROR  (default: INFO)

Examples:
    # Search with a Java backend JD:
    python -m phase2.search --job jobs/backend-engineer-001.txt

    # Search and request top 50 candidates:
    python -m phase2.search --job jobs/backend-engineer-001.txt --top-k 50

    # Use wider retrieval for better recall:
    python -m phase2.search --job jobs/backend-engineer-001.txt \\
        --lexical-top-k 50 --vector-top-k 50 --top-k 100
"""
from phase2.retrieval.hybrid_search import main

if __name__ == "__main__":
    main()
