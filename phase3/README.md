# Phase 3 — Semantic Candidate Reranking

## Overview
Phase 3 builds upon the rapid hybrid candidate retrieval performed in Phase 2. While Phase 2 narrows down thousands of resumes into a small shortlist (e.g., top 15) using BM25 and Vector Search, **Phase 3 semantically reranks that shortlist using Voyage AI's cross-encoder model (`rerank-2.5`).**

## Architecture Recap
1. **Input**: Phase 2 retrieval JSON (`outputs/<job-id>-retrieval.json`) & Job Description text.
2. **Document Reconstruction**: Chunks are pulled from MongoDB Atlas and stitched back together into a readable candidate profile to give the cross-encoder full context.
3. **Reranking**: The Voyage API scores the Job Description (Query) against each Candidate Profile (Document).
4. **Output**: A final JSON containing the new semantic ranks alongside Phase 2 provenance metadata.

## Setup
Ensure you have set up your `.env` file according to `.env.example`. Phase 3 requires the same `VOYAGE_API_KEY` and `MONGODB_URI` as Phase 2.

```env
VOYAGE_RERANK_MODEL=rerank-2.5
RERANK_TOP_K=-1
RERANK_MAX_DOCUMENT_CHARS=30000
```

## Running the Reranker
The reranker reads the Phase 2 output and processes the candidates.

```powershell
python -m phase3.rerank --job jobs/backend-engineer-001.txt --input outputs/backend-engineer-001-retrieval.json
```

**Options**:
- `--top-k 5`: Limit output to the top 5 reranked candidates.
- `--model rerank-2.5`: Override the Voyage model.

## Outputs
1. **`outputs/<job-id>-reranked.json`**: The core deliverable for Phase 4. Contains candidates sorted by relevance, with Phase 2 provenance intact.
2. **`outputs/<job-id>-rerank-evaluation.json`**: A summary report containing processing times, failure counts, and score distributions for local validation.
