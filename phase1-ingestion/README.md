# Phase 1 ingestion

## Planned resources and cost review

The deployment creates one private S3 bucket, two Python 3.13 Lambda functions, one standard SNS topic, three least-privilege IAM roles, two SNS/S3 Lambda permissions, and automatic CloudWatch log groups when the functions first run. All resources are in `ap-south-1`.

The potentially billable services are Textract (per PDF page), S3 storage/requests, Lambda requests/duration, SNS notifications, and Lambda-generated CloudWatch Logs. Free Tier eligibility depends on the account and current AWS terms; any overage can consume AWS credits. No always-running resources are created. See `../docs/aws-cost-control.md`.

## Prerequisites

- AWS CLI v2 installed and authenticated to the intended personal account.
- Permission to create the resources named above in `ap-south-1`.
- A globally unique, lowercase bucket name, for example `ai-resume-screening-dev-yourinitials-20260916`.

## Deploy (after cost approval)

From `phase1-ingestion/infrastructure`, run `./deploy.ps1 -BucketName <unique-bucket-name> -Apply`. It validates the template first, deploys one CloudFormation stack, refuses a configured non-`ap-south-1` region, and does not upload test resumes.

## Test one PDF

Upload exactly one non-sensitive test PDF:

```powershell
aws s3 cp .\test-resume.pdf s3://<bucket>/incoming/test-resume.pdf --region ap-south-1
```

Wait for the asynchronous job, then list and download `s3://<bucket>/extracted/`. The JSON includes the JobId, original S3 path, complete raw `Blocks`, normalized `text`, page count, and processing metadata. Uploading DOCX, PNG, JPG, or a PDF outside `incoming/` does not trigger processing.

## Delete

Use `infrastructure/cleanup.ps1 -BucketName <bucket>`. It asks for explicit confirmation, deletes both stacks, and empties only the named project bucket. Do not run it if it contains resumes you need to retain.
