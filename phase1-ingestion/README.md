# Phase 1 — Asynchronous PDF Resume Ingestion & Text Extraction

## Overview

Phase 1 provides a fully serverless, event-driven ingestion pipeline that automatically extracts raw text and layout blocks from PDF resumes using **Amazon Textract**.

When a PDF resume is uploaded to Amazon S3, an asynchronous Textract job is initiated. Upon completion, an Amazon SNS notification invokes a collector Lambda function that paginates through all Textract document blocks, extracts line-level text, and stores a structured JSON document back into Amazon S3.

Phase 1 does **not** perform text chunking, embedding generation, database indexing, or candidate ranking. Those capabilities belong to **Phase 2** (Hybrid Retrieval) and **Phase 3** (Semantic Reranking).

---

## Architecture & Event-Driven Pipeline

Phase 1 operates completely asynchronously with zero always-running servers:

```mermaid
flowchart TD
    User([Candidate / Recruiter / API]) -->|Uploads PDF| S3In[(S3: incoming/*.pdf)]
    S3In -->|s3:ObjectCreated Event| LambdaStart[Lambda: resume-start-textract]
    LambdaStart -->|StartDocumentTextDetection| Textract[Amazon Textract]
    Textract -->|Processes Pages Asynchronously| Textract
    Textract -->|Publishes Job Status| SNSTopic[SNS: resume-textract-completed]
    SNSTopic -->|Triggers| LambdaCollect[Lambda: resume-collect-textract]
    LambdaCollect -->|GetDocumentTextDetection (Paginated)| Textract
    LambdaCollect -->|Writes Extracted JSON| S3Out[(S3: extracted/{job_id}.json)]
    LambdaCollect -.->|On Failure| S3Fail[(S3: failed/{job_id}.json)]
```

### Pipeline Flow:
1. **Upload:** A PDF is placed in `s3://<bucket>/incoming/`.
2. **Trigger 1:** S3 detects the object creation and invokes `resume-start-textract`.
3. **Initiation:** The start function validates the file prefix (`incoming/`) and file extension (`.pdf`), then calls Textract's `StartDocumentTextDetection`.
4. **Processing:** Amazon Textract performs OCR across all pages asynchronously in the background.
5. **Notification:** Textract publishes completion status to the `resume-textract-completed` SNS topic.
6. **Trigger 2:** SNS invokes `resume-collect-textract`.
7. **Extraction & Storage:** The collector function loops through all paginated blocks via `GetDocumentTextDetection`, reconstructs full text lines, and saves a comprehensive output file to `s3://<bucket>/extracted/<job_id>.json`.

---

## Prerequisites

| Tool / Service | Version / Requirement | Notes |
|---|---|---|
| **Python** | 3.13 | Native runtime used by both Lambda functions |
| **AWS CLI** | v2 | Configured with credentials for the `ap-south-1` (Mumbai) region |
| **AWS Account** | Active with Free Tier or Credits | Must have permissions for S3, Lambda, Textract, SNS, IAM, and CloudWatch |
| **PowerShell** | 5.1+ or Core 7+ | For running deployment and testing helper scripts |

---

## Repository Structure (Phase 1)

```
phase1-ingestion/
  README.md                          ← This detailed guide
  infrastructure/
    phase1.yaml                      ← CloudFormation template (infrastructure-as-code)
    deploy.ps1                       ← Automated validation and deployment script
    cleanup.ps1                      ← Teardown and bucket wipe script
    README.md                        ← Infrastructure-specific notes
  lambda-start-textract/
    lambda_function.py               ← Initiates Textract async job on S3 upload
  lambda-collect-textract/
    lambda_function.py               ← Collects paginated Textract results & saves JSON
  tests/
    README.md                        ← Verification instructions & sample test cases
```

---

## AWS Resources & Components

The Phase 1 CloudFormation stack (`ai-resume-screening-phase1`) provisions the following least-privilege resources:

| Logical Resource | AWS Service | Purpose |
|---|---|---|
| `ResumeBucket` | Amazon S3 | Single private bucket with SSE-AES256 encryption and public access blocks. |
| `StartFunction` | AWS Lambda (`python3.13`) | Validates S3 events and starts asynchronous Textract document analysis. |
| `CollectFunction` | AWS Lambda (`python3.13`) | Gathers Textract blocks, stitches lines of text, and saves JSON outputs. |
| `CompletionTopic` | Amazon SNS | Decoupled notification topic receiving Textract completion events. |
| `TextractSnsRole` | AWS IAM Role | Granted `sns:Publish` to send notifications from Textract to SNS. |
| `StartRole` | AWS IAM Role | Allows reading `incoming/*` PDFs and executing `textract:StartDocumentTextDetection`. |
| `CollectRole` | AWS IAM Role | Allows reading Textract results and writing to `extracted/*` and `failed/*`. |
| `AllowS3InvokeStart` | Lambda Permission | Authorizes S3 to invoke the start Lambda on `incoming/*.pdf` uploads. |
| `AllowSnsInvokeCollect`| Lambda Permission | Authorizes SNS to invoke the collector Lambda on message publication. |

---

## S3 Folder Hierarchy

The bucket (`ai-resume-screening-dev-761595200930`) uses strict prefix partitioning:

```
s3://<bucket>/
  ├── incoming/                      ← Raw PDF resume uploads (triggers Phase 1)
  │     ├── resume-01.pdf
  │     └── saas__<tenant>__<job>__<app>.pdf
  │
  ├── extracted/                     ← Successfully extracted JSON files (Phase 1 output)
  │     └── <textract-job-id>.json
  │
  └── failed/                        ← JSON error records if Textract fails
        └── <textract-job-id>.json
```

> [!NOTE]
> The `resume-start-textract` Lambda enforces a strict filter: any file not located under `incoming/` or not ending with `.pdf` is ignored with the log message `Rejected non-Phase-1 S3 event`.

---

## Extracted JSON Schema (`extracted/<job_id>.json`)

When Textract completes, the collector Lambda writes a structured JSON document formatted as follows:

```json
{
  "job_id": "18e12c6530ee3a69b386ecbaa37b8b4ebbe51780c1564887b73544a4a40b64b2",
  "status": "SUCCEEDED",
  "source": {
    "bucket": "ai-resume-screening-dev-761595200930",
    "key": "incoming/Daniel_Leve_Resume.pdf"
  },
  "page_count": 2,
  "text": "DANIEL LEVE\nSoftware Engineer\nSummary\nExperienced backend developer...\nSkills\nPython, AWS, MongoDB...\nExperience\nGoogle - Software Engineer...\nEducation\nB.S. in Computer Science...",
  "blocks": [
    {
      "BlockType": "PAGE",
      "Id": "block-page-1",
      "Geometry": { ... }
    },
    {
      "BlockType": "LINE",
      "Id": "block-line-1",
      "Text": "DANIEL LEVE",
      "Confidence": 99.8
    }
  ],
  "metadata": {
    "processed_at": "2026-09-21T16:30:40.123456+00:00",
    "pipeline_version": "phase1-v1"
  }
}
```

### Key Fields:
* `job_id`: The unique AWS Textract execution ID.
* `source.key`: The original S3 key of the PDF. In SaaS mode, this holds encoded tenant, job, and candidate identifiers (`incoming/saas__<tid>__<jid>__<aid>.pdf`).
* `page_count`: Total number of pages extracted from the PDF.
* `text`: Clean, newline-delimited text containing all recognized `LINE` blocks, ready for NLP parsing.
* `blocks`: The complete raw array of Textract blocks (LINE, WORD, PAGE) with bounding box geometry and confidence scores.

---

## Deployment Guide

### Deploying the CloudFormation Stack

From PowerShell at the project root (`d:\ResumeProjCodex`):

```powershell
# Navigate to infrastructure directory
cd phase1-ingestion\infrastructure

# 1. Validate template (Dry Run)
.\deploy.ps1 -BucketName ai-resume-screening-dev-761595200930

# 2. Deploy to AWS ap-south-1
.\deploy.ps1 -BucketName ai-resume-screening-dev-761595200930 -Apply
```

The script:
1. Validates `phase1.yaml` with the AWS CloudFormation engine.
2. Verifies that your configured AWS CLI region is `ap-south-1`.
3. Creates or updates the CloudFormation stack with `CAPABILITY_NAMED_IAM`.

---

## Testing & Verification

### Step 1: Upload a Sample PDF

Upload a test PDF into the `incoming/` directory of the bucket:

```powershell
aws s3 cp .\sample-resume.pdf s3://ai-resume-screening-dev-761595200930/incoming/sample-resume.pdf --region ap-south-1
```

### Step 2: Monitor Lambda Execution in CloudWatch

Watch the start function logs:
```powershell
aws logs tail /aws/lambda/resume-start-textract --follow --region ap-south-1
```
*Expected log:* `{'event': 'textract_started', 'bucket': '...', 'key': 'incoming/sample-resume.pdf', 'job_id': '...'}`

Watch the collector function logs:
```powershell
aws logs tail /aws/lambda/resume-collect-textract --follow --region ap-south-1
```
*Expected log:* `{'event': 'textract_collected', 'job_id': '...', 'block_count': 342}`

### Step 3: Verify the Output JSON in S3

List and download the newly created extraction JSON:

```powershell
# List extracted files
aws s3 ls s3://ai-resume-screening-dev-761595200930/extracted/ --region ap-south-1

# Download the latest output
aws s3 cp s3://ai-resume-screening-dev-761595200930/extracted/ <local-folder> --recursive --region ap-south-1
```

---

## Error Handling & Resilience

1. **Non-PDF / Wrong Folder Rejection:**
   If a file is placed outside `incoming/` or does not end with `.pdf`, `resume-start-textract` logs `Rejected non-Phase-1 S3 event` and gracefully halts execution without calling Textract.
2. **Textract Job Failures:**
   If Textract fails to process a corrupt or encrypted document, the collector Lambda captures the failure event and writes diagnostic metadata to `s3://<bucket>/failed/<job_id>.json`.
3. **Paging Resilience:**
   `resume-collect-textract` loops through all `NextToken` pages returned by Textract, ensuring multi-page resumes (up to 30+ pages) are completely retrieved without data truncation.
4. **Encryption at Rest:**
   All S3 outputs written by the collector use server-side encryption (`AES256`).

---

## Handoff to Phase 2 (Hybrid Retrieval)

Phase 1 terminates once `extracted/<job_id>.json` is saved in S3. 

From here:
* In the **Local CLI Prototype**, Phase 2 downloads files from `extracted/` and runs `python -m phase2.index_resumes`.
* In the **Serverless SaaS System**, S3 sends an `ObjectCreated` event for `extracted/*.json` to the SQS `resume-indexing-dev` queue, waking up the `IndexingWorker` Lambda to chunk text and generate Voyage AI vector embeddings.

---

## Teardown & Resource Cleanup

To remove all Phase 1 AWS resources:

```powershell
cd phase1-ingestion\infrastructure
.\cleanup.ps1 -BucketName ai-resume-screening-dev-761595200930
```

> [!CAUTION]
> Running `cleanup.ps1` empties the specified S3 bucket and deletes the CloudFormation stack. Only run this if you intend to destroy all extracted resume data and infrastructure.
