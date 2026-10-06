# Phase 1 Architecture — Asynchronous PDF Resume Text Extraction

> **Note:** For the comprehensive Phase 1 architecture guide, please refer to [`phase1-architecture.md`](file:///d:/ResumeProjCodex/docs/phase1-architecture.md).

## Quick Overview

Phase 1 takes an uploaded PDF resume, runs it through **Amazon Textract** OCR asynchronously, and outputs a clean JSON file containing normalized line text and layout blocks to `s3://<bucket>/extracted/<job-id>.json`.

```
[ Upload PDF ] ──> S3 incoming/ ──> Lambda (start) ──> Textract (OCR)
                                                            │
[ Phase 2 ] <── S3 extracted/ <── Lambda (collect) <── SNS (done)
```

See the full detailed guide with step-by-step component explanations, cost considerations, and error handling in [**docs/phase1-architecture.md**](file:///d:/ResumeProjCodex/docs/phase1-architecture.md).
