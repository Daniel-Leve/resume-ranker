# AI-Powered Resume Screening

This repository implements a multi-phase AI-powered resume screening system.

- **Phase 1**: Private PDF resume ingestion, asynchronous Amazon Textract text detection, and an explainable raw extraction result.
- **Phase 2**: Hybrid candidate retrieval via MongoDB Atlas Search (BM25) and Atlas Vector Search (Voyage AI embeddings) with Reciprocal Rank Fusion.
- Phases 3–5 are intentionally not implemented.

See [phase1-ingestion/README.md](phase1-ingestion/README.md) for Phase 1 deployment and testing.
See [phase2/README.md](phase2/README.md) for Phase 2 setup, MongoDB indexing, and hybrid search commands.
See [docs/phase2-architecture.md](docs/phase2-architecture.md) for Phase 2 architectural design.
See [docs/architecture.md](docs/architecture.md) for the Phase 1 event flow.
See [docs/aws-cost-control.md](docs/aws-cost-control.md) before creating AWS resources.
