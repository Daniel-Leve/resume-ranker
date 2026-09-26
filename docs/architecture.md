# Phase 1 architecture

`incoming/*.pdf` in the private S3 bucket triggers `resume-start-textract`. The function validates the key and starts `StartDocumentTextDetection`, directing completion to the standard SNS topic. SNS invokes `resume-collect-textract`, which retrieves every result page, normalizes `LINE` blocks, and writes `extracted/<job-id>.json`. Textract failures become `failed/<job-id>.json`.

Only the `incoming/` prefix and `.pdf` suffix are wired to S3 events. Unsupported formats never invoke the start function.
