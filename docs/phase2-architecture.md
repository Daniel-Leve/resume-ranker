# Phase 2 Architecture — Hybrid Candidate Retrieval

## Overview

Phase 2 is a local Python pipeline that takes Phase 1's extracted resume text
and makes it searchable by a recruiter-supplied job description via two
complementary retrieval methods fused together.

---

## Event Flow

```
Phase 1 S3 bucket
  extracted/<textract-job-id>.json
            │
            │  boto3.get_object (read-only)
            ▼
   Python Indexing Worker
   (python -m phase2.index_resumes)
            │
            ├── Derive candidate_id from source.key
            │     "incoming/john-doe.pdf" → "john-doe"
            │
            ├── Compute SHA-256(text)  → content_hash
            │     Skip if hash unchanged  (idempotency)
            │
            ├── Deterministic Section-Aware Chunker
            │     Regex section headers: Summary, Skills, Experience,
            │     Projects, Education, Certifications, Achievements…
            │     Split large sections at char limit (1200 chars default)
            │     Fallback to fixed-size window for plain resumes
            │     Annotate page_start/page_end from Textract blocks
            │
            └── Voyage AI  voyage-4-large  (input_type="document")
                  72-text batches, exponential backoff retry
                  1024-dimensional embeddings
                        │
                        ▼
              MongoDB Atlas  resume_screening.candidate_chunks
              (upsert by chunk_id)

─────────────────────────────────────────────────────────────────────

Recruiter provides Job Description (.txt)
            │
            ▼
   Python Search Worker
   (python -m phase2.search --job jobs/backend-engineer-001.txt)
            │
            ├── Normalise JD text
            │
            ├── Voyage AI  voyage-4-large  (input_type="query")
            │     Single API call for the job description embedding
            │
    ┌───────┴────────────────────┐
    ▼                            ▼
MongoDB Atlas Search        MongoDB Atlas Vector Search
  $search (text operator)     $vectorSearch
  lucene.standard analyser    cosine similarity
  BM25 relevance scoring      1024-dim embedding space
  top LEXICAL_TOP_K chunks    top VECTOR_TOP_K chunks
    │                            │
    └──────────────┬─────────────┘
                   ▼
         Reciprocal Rank Fusion
           score(doc) = Σ  1 / (rank_i + 60)
           across all result lists where doc appears

           Deduplicate by candidate_id
           (multi-chunk candidate → single result)

           Preserve provenance:
             lexical_rank   (best rank in BM25 list)
             vector_rank    (best rank in vector list)
             matched_chunks (all contributing chunk_ids + sections)
                   │
                   ▼
          Top FINAL_TOP_K unique candidates
          (with full retrieval provenance)
                   │
                   ▼
     outputs/<job-id>-retrieval.json
     (consumed by Phase 3)
```

---

## MongoDB Collection: `candidate_chunks`

```
_id              = chunk_id  (e.g. "john-doe_experience_00")
candidate_id     = "john-doe"
chunk_id         = "john-doe_experience_00"
source_key       = "extracted/<textract-job-id>.json"
chunk_index      = 2
section          = "experience"
text             = "Senior Software Engineer..."
embedding_model  = "voyage-4-large"
embedding_dims   = 1024
embedding        = [float × 1024]
content_hash     = sha256(full_resume_text)   ← idempotency key
metadata:
  page_start     = 1
  page_end       = 2
  source_s3_bucket = "ai-resume-screening-dev-..."
```

---

## MongoDB Indexes

### Operational indexes (created by indexer automatically)
| Name | Fields | Purpose |
|---|---|---|
| `idx_source_key_hash` | `(source_key, content_hash)` | Fast idempotency check |
| `idx_candidate_id` | `candidate_id` | Fast chunk deletion on re-index |

### Atlas Search index (created manually in Atlas UI)
| Name | Field | Type | Analyser |
|---|---|---|---|
| `text_search_index` | `text` | string | lucene.standard (BM25) |

### Atlas Vector Search index (created manually in Atlas UI)
| Name | Field | Dimensions | Similarity |
|---|---|---|---|
| `vector_search_index` | `embedding` | 1024 | cosine |

---

## RRF Fusion — Design Rationale

Reciprocal Rank Fusion was chosen over score normalisation because:

1. **No score calibration needed**: BM25 scores and cosine similarity scores
   are on different scales.  RRF uses only rank positions, not raw scores.

2. **Robust to outliers**: A single extremely high BM25 score does not
   overwhelm the vector results.

3. **Proven empirically**: Cormack et al. (2009) showed RRF matches or
   outperforms more complex fusion methods with k=60.

4. **Multi-chunk accumulation**: A candidate whose multiple chunks all rank
   high naturally accumulates more score — this is desirable behaviour, not
   a bug.

---

## Chunking — Design Rationale

Section-aware chunking (vs. naive fixed-size) improves retrieval because:

1. **Semantic coherence**: A "skills" chunk is semantically distinct from an
   "experience" chunk.  Vector search finds relevant *sections*, not
   fragmented context.

2. **BM25 precision**: Term frequency within a focused section is more
   informative than term frequency across a mixed window.

3. **Explainability**: Section labels in `matched_chunks` tell Phase 3 *why*
   a candidate was retrieved (e.g. matched on "skills" section).

4. **Cost efficiency**: Section boundaries produce naturally-sized chunks
   without aggressive overlap, reducing embedding token costs.

---

## Phase 1 → Phase 2 Compatibility

| Phase 1 field | Phase 2 usage |
|---|---|
| `status` | Skip non-SUCCEEDED records |
| `source.key` | Derive `candidate_id` from PDF filename |
| `text` | Primary input to chunker and content hash |
| `blocks` | PAGE/LINE blocks used for `page_start`/`page_end` annotation |
| `job_id` | Used as part of the S3 key (`extracted/<job_id>.json`) |

Phase 1 is **not modified** by Phase 2.

---

## Phase 3 Interface

The `outputs/<job-id>-retrieval.json` file is Phase 3's input:

- Each candidate entry carries `source_key` so Phase 3 can retrieve the
  original extraction from S3 if needed for full-text analysis.
- `matched_chunks[].section` tells Phase 3 which resume sections matched
  — a foundation for explainable ranking.
- `hybrid_score` gives Phase 3 an initial ordering to refine with reranking.
