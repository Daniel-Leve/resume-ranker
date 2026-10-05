# AI-Powered Resume Screening

This repository implements a multi-phase AI-powered resume screening system.

- **Phase 1**: Private PDF resume ingestion, asynchronous Amazon Textract text detection, and an explainable raw extraction result.
- **Phase 2**: Hybrid candidate retrieval via MongoDB Atlas Search (BM25) and Atlas Vector Search (Voyage AI embeddings) with Reciprocal Rank Fusion.
- **Phase 3**: Semantic reranking of the Phase 2 candidate pool using Voyage `rerank-2.5`.
- **SaaS Layer (Phase A+B)**: Multi-tenant data model, AWS SAM infrastructure (`template.yaml`), REST API Lambda handler, and async SQS-driven indexing/screening workers.
- Phases 4–5 are intentionally not implemented.

See [phase1-ingestion/README.md](phase1-ingestion/README.md) for Phase 1 deployment and testing.
See [phase2/README.md](phase2/README.md) for Phase 2 setup, MongoDB indexing, and hybrid search commands.
See [phase3/README.md](phase3/README.md) for Phase 3 reranking commands.
See [docs/phase2-architecture.md](docs/phase2-architecture.md) for Phase 2 architectural design.
See [docs/phase3-architecture.md](docs/phase3-architecture.md) for Phase 3 architectural design.
See [docs/architecture.md](docs/architecture.md) for the Phase 1 event flow.
See [docs/aws-cost-control.md](docs/aws-cost-control.md) before creating AWS resources.
