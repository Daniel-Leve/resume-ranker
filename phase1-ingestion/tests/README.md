# Phase 1 test plan

Run only one to five non-sensitive sample PDFs initially.

1. Upload a valid one-page PDF to `incoming/`; verify an extraction JSON result.
2. Upload a valid multi-page PDF; verify `page_count`, all raw blocks, and normalized line text.
3. Upload DOCX to `incoming/`; verify that Lambda is not invoked.
4. Upload PNG/JPG to `incoming/`; verify that Lambda is not invoked.
5. Optionally upload an empty/invalid PDF; verify a clear start-function failure log with no resume text exposed.
