# Phase 2 — Hybrid Candidate Retrieval

## Overview

Phase 2 reads the Phase 1 extracted resume JSON files from S3, builds
section-aware embeddings with Voyage AI (`voyage-4-large`), stores them in
MongoDB Atlas, and retrieves the most relevant candidates for a given job
description using a BM25 + vector hybrid search with Reciprocal Rank Fusion.

Phase 2 does **not** perform reranking, scoring explainability, or candidate
communication. Those belong to later phases.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13 | Match the Phase 1 Lambda runtime |
| AWS CLI | v2 | Authenticated; `ap-south-1` region |
| Voyage AI | API key | From [voyageai.com](https://www.voyageai.com/) or MongoDB Atlas integration |
| MongoDB Atlas | Free cluster (M0) | Atlas Search + Vector Search enabled |

---

## Repository structure (Phase 2)

```
phase2/                   ← Python package (importable as `phase2`)
  __init__.py
  config.py               ← All settings from environment variables
  index_resumes.py        ← CLI entry: python -m phase2.index_resumes
  search.py               ← CLI entry: python -m phase2.search
  indexer/
    chunker.py            ← Section-aware deterministic chunker
    embedder.py           ← Voyage AI batched embedding client
    index_resumes.py      ← Core indexing logic
  retrieval/
    lexical_search.py     ← MongoDB Atlas Search (BM25)
    vector_search.py      ← MongoDB Atlas Vector Search (cosine)
    fusion.py             ← Reciprocal Rank Fusion
    hybrid_search.py      ← Core search logic
  models/
    schemas.py            ← CandidateChunk, RetrievalResult, HybridSearchOutput
  tests/
    test_chunker.py
    test_fusion.py
    fixtures/
      sample_extracted.json
  requirements.txt
  requirements-dev.txt
  README.md               ← This file

jobs/                     ← Job description .txt files
  backend-engineer-001.txt
  python-data-engineer-001.txt

outputs/                  ← Generated retrieval JSONs (git-ignored)

.env.example              ← Template — copy to .env, fill in secrets
```

---

## Installation

From the project root (`d:\ResumeProjCodex`):

```powershell
# Create and activate a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install Phase 2 dependencies
pip install -r phase2/requirements.txt

# Install dev/test dependencies (optional)
pip install -r phase2/requirements-dev.txt
```

---

## Environment Setup

Copy `.env.example` to `.env` and fill in your credentials:

```powershell
copy .env.example .env
# Edit .env with your real VOYAGE_API_KEY, MONGODB_URI, and S3_BUCKET_NAME
```

### Required environment variables

| Variable | Description |
|---|---|
| `VOYAGE_API_KEY` | Your Voyage AI API key |
| `MONGODB_URI` | MongoDB Atlas connection string (SRV format) |
| `S3_BUCKET_NAME` | Phase 1 S3 bucket (`ai-resume-screening-dev-761595200930`) |

### Optional (with defaults)

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `ap-south-1` | AWS region |
| `VOYAGE_MODEL` | `voyage-4-large` | Embedding model |
| `VOYAGE_EMBEDDING_DIMENSIONS` | `1024` | Output dimensions |
| `VOYAGE_BATCH_SIZE` | `72` | Texts per API call |
| `MONGODB_DATABASE` | `resume_screening` | Database name |
| `MONGODB_COLLECTION` | `candidate_chunks` | Collection name |
| `VECTOR_INDEX_NAME` | `vector_search_index` | Atlas Vector Search index name |
| `TEXT_INDEX_NAME` | `text_search_index` | Atlas Search index name |
| `LEXICAL_TOP_K` | `15` | BM25 chunk retrieval depth |
| `VECTOR_TOP_K` | `15` | Vector search chunk retrieval depth |
| `FINAL_TOP_K` | `15` | Final unique candidates returned |
| `RRF_K` | `60` | RRF smoothing constant |
| `MAX_CHUNK_CHARS` | `1200` | Max chars per chunk before splitting |

---

## MongoDB Atlas Index Setup

> [!IMPORTANT]
> The Atlas Search and Vector Search indexes **cannot** be created via PyMongo.
> They must be created manually in the Atlas web UI **after** the collection
> is first populated (run `index_resumes` at least once first).

### Step 1 — Create the Atlas Vector Search index

1. Log in to [cloud.mongodb.com](https://cloud.mongodb.com).
2. Navigate to your cluster → **Atlas Search** tab → **Create Search Index**.
3. Choose **Atlas Vector Search** → **JSON Editor**.
4. Select database `resume_screening`, collection `candidate_chunks`.
5. Paste this definition and name the index `vector_search_index`:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    }
  ]
}
```

6. Click **Create** and wait for the index to become **Active** (can take 1–3 minutes on a free cluster).

### Step 2 — Create the Atlas Search (full-text) index

1. In the same **Atlas Search** tab → **Create Search Index**.
2. Choose **Atlas Search** → **JSON Editor**.
3. Select `resume_screening.candidate_chunks`.
4. Paste this definition and name the index `text_search_index`:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "text": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "candidate_id": {
        "type": "string"
      },
      "section": {
        "type": "string"
      }
    }
  }
}
```

5. Click **Create** and wait for **Active** status.

> [!NOTE]
> On a Free (M0) cluster, you are limited to 3 search indexes total.
> Phase 2 uses 2 (one vector, one full-text).

---

## Running the Indexer

```powershell
# Index all resumes from Phase 1 S3 bucket
python -m phase2.index_resumes

# Dry run — see what would be indexed without writing anything
python -m phase2.index_resumes --dry-run

# Force re-index a single candidate (useful after re-extraction)
python -m phase2.index_resumes --candidate john-doe --force

# Verbose debug output
python -m phase2.index_resumes --log-level DEBUG
```

**Expected output (INFO level):**

```
2026-09-21T15:00:00 [INFO] phase2.indexer.index_resumes: === Phase 2 Indexer ===
2026-09-21T15:00:00 [INFO] phase2.indexer.index_resumes: Source:  s3://ai-resume-screening-dev.../extracted/
2026-09-21T15:00:01 [INFO] phase2.indexer.index_resumes: Found 8 JSON files in s3://...
2026-09-21T15:00:02 [INFO] phase2.indexer.index_resumes: Candidate john-doe: 5 chunk(s) | sections: ['summary', 'skills', 'experience', 'education', 'certifications']
2026-09-21T15:00:04 [INFO] phase2.indexer.index_resumes: Candidate john-doe: indexed 5 chunk(s).
...
2026-09-21T15:00:30 [INFO] phase2.indexer.index_resumes: Indexing complete.
2026-09-21T15:00:30 [INFO] phase2.indexer.index_resumes:   Candidates found:         8
2026-09-21T15:00:30 [INFO] phase2.indexer.index_resumes:   Newly indexed:            8
2026-09-21T15:00:30 [INFO] phase2.indexer.index_resumes:   Total chunks stored:     42
```

### Idempotency

Re-running the indexer on **unchanged** resumes produces:
```
Candidate john-doe: unchanged — skipping (hash match).
```

No new embeddings are generated and no Voyage API calls are made.

---

## Running Hybrid Search

```powershell
# Search with the Java backend JD
python -m phase2.search --job jobs/backend-engineer-001.txt

# Request up to 50 candidates
python -m phase2.search --job jobs/backend-engineer-001.txt --top-k 50

# Wider retrieval for better recall on a large corpus
python -m phase2.search --job jobs/backend-engineer-001.txt `
    --lexical-top-k 50 --vector-top-k 50 --top-k 100

# Python data engineer JD
python -m phase2.search --job jobs/python-data-engineer-001.txt
```

Results are written to `outputs/<job-id>-retrieval.json`.

**Example output:**

```json
{
  "job_id": "backend-engineer-001",
  "retrieval_method": "hybrid",
  "embedding_model": "voyage-4-large",
  "embedding_dimensions": 1024,
  "parameters": {
    "lexical_top_k": 15,
    "vector_top_k": 15,
    "final_top_k": 15,
    "rrf_k": 60
  },
  "total_candidates": 5,
  "candidates": [
    {
      "candidate_id": "john-doe",
      "hybrid_score": 0.030328,
      "retrieval": {
        "lexical_rank": 1,
        "vector_rank": 2
      },
      "matched_chunks": [
        {"chunk_id": "john-doe_experience_00", "section": "experience"},
        {"chunk_id": "john-doe_skills_00", "section": "skills"}
      ],
      "source_key": "extracted/abc123textractjobid456.json"
    }
  ]
}
```

---

## Running Unit Tests

```powershell
# From project root — no credentials needed for unit tests
python -m pytest phase2/tests/ -v

# With coverage (if pytest-cov installed)
python -m pytest phase2/tests/ -v --tb=short
```

Unit tests cover:
- Section header detection (23+ patterns)
- Section-aware chunking, large-section splitting, fallback chunking
- Page metadata from Textract blocks
- Idempotency (same text → same chunk_ids)
- Content hash stability
- Candidate ID derivation
- RRF score mathematics
- Multi-chunk deduplication
- Null rank integrity
- Score ordering and determinism

---

## Chunking Strategy

The chunker (`phase2/indexer/chunker.py`) uses **deterministic, regex-based section detection**:

1. **Header detection**: Each line is matched against 12 section header patterns
   covering: Summary, Skills, Experience, Projects, Education, Certifications,
   Achievements, Publications, Languages, Volunteer, and Interests.

2. **Section grouping**: Lines are accumulated under each detected header.
   The unnamed leading block (name, contact info) is labelled `"header"`.

3. **Large-section splitting**: Sections exceeding `MAX_CHUNK_CHARS` (1200 chars)
   are split at line boundaries. Chunk IDs use zero-padded suffix:
   `john-doe_experience_00`, `john-doe_experience_01`, etc.

4. **Fallback**: If no section headers are detected (very plain resume),
   the text is split into `_FALLBACK_CHUNK_CHARS` (1000 char) windows with
   100-char overlap. All chunks are labelled `section="unknown"`.

5. **Page annotation**: Chunk `page_start` and `page_end` are derived from
   the Textract `blocks` array included in every Phase 1 JSON.

---

## Hybrid Retrieval Architecture

```
Job Description (.txt)
        │
        ▼
  Normalise text
        │
        ▼
  Voyage AI embed()              input_type = "query"
  (voyage-4-large, 1024 dims)
        │
   ┌────┴─────────────────┐
   ▼                       ▼
MongoDB Atlas Search    MongoDB Atlas Vector Search
  $search (BM25)          $vectorSearch (cosine)
  text_search_index       vector_search_index
  top LEXICAL_TOP_K       top VECTOR_TOP_K chunk hits
        │                       │
        └──────────┬────────────┘
                   ▼
         Reciprocal Rank Fusion
         score = Σ 1/(rank + 60)
         deduplicate by candidate_id
                   │
                   ▼
          Top FINAL_TOP_K
          unique candidates
          (with provenance)
                   │
                   ▼
     outputs/<job-id>-retrieval.json
```

---

## MongoDB Collection Schema

Collection: `resume_screening.candidate_chunks`

```json
{
  "_id": "john-doe_experience_00",
  "candidate_id": "john-doe",
  "chunk_id": "john-doe_experience_00",
  "source_key": "extracted/<textract-job-id>.json",
  "chunk_index": 2,
  "section": "experience",
  "text": "Senior Software Engineer - Acme Technologies...",
  "embedding_model": "voyage-4-large",
  "embedding_dimensions": 1024,
  "embedding": [0.012, -0.034, ...],
  "content_hash": "sha256hex...",
  "metadata": {
    "page_start": 1,
    "page_end": 2,
    "source_s3_bucket": "ai-resume-screening-dev-761595200930"
  }
}
```

---

## Known Limitations

1. **Small test corpus** (5–20 resumes): `FINAL_TOP_K=15` will often return
   fewer candidates than requested. This is expected and logged as a warning.

2. **Atlas Search index latency**: After creating the index in the Atlas UI,
   it can take 1–5 minutes to become active. The indexer can run before the
   search indexes are ready; only the search command needs them.

3. **Free cluster index limits**: M0 clusters support up to 3 Atlas Search
   indexes. Phase 2 uses 2 (vector + text), leaving 1 for future use.

4. **No cross-encoder reranking**: Phase 2 output is an initial candidate pool.
   Final ranking quality improves in Phase 3 (Voyage reranking).

5. **Candidate ID collisions**: If two PDFs have the same filename, they will
   map to the same `candidate_id`. Use distinct filenames when uploading.

---

## Cost Considerations

| Service | Phase 2 usage | Expected cost |
|---|---|---|
| Voyage AI | ~1K tokens per chunk × N chunks (indexing) | Free trial or low paid cost |
| MongoDB Atlas | Storage + search queries on Free cluster | Free (M0) |
| AWS S3 | Read-only `GetObject` calls during indexing | Negligible (<$0.01) |
| AWS EC2/ECS | None — runs locally | $0 |

No new AWS infrastructure is created.

---

## Security

- `VOYAGE_API_KEY` and `MONGODB_URI` must only appear in your local `.env` file.
- `.env` is listed in `.gitignore` and will never be committed.
- MongoDB user should have `readWrite` on `resume_screening` database only —
  not `atlasAdmin` or cluster-wide roles.
- Logs never contain resume text, email addresses, phone numbers, or addresses.

---

## Phase 3 Compatibility

The `outputs/<job-id>-retrieval.json` file is designed for Phase 3 consumption.
Each candidate entry includes:
- `candidate_id` for lookup
- `hybrid_score` as the initial ranking signal
- `retrieval.lexical_rank` and `retrieval.vector_rank` for provenance
- `matched_chunks` with `chunk_id` and `section` for explainability
- `source_key` to retrieve the original Phase 1 extraction from S3
