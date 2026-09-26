# AWS cost control

## What can cost money

| Resource | Cost basis | Free Tier / credits |
| --- | --- | --- |
| Textract async text detection | Pages processed | Charges per page; AWS Free Tier eligibility depends on account age and service offer. Otherwise consumes account credits. |
| S3 | Stored GB-month, requests, and data transfer | Small test PDFs/results usually fit Free Tier; charges can consume credits. |
| Lambda | Requests and GB-seconds | Eligible monthly Free Tier; overage consumes credits. |
| SNS | Publish/delivery requests | Eligible Free Tier limits may apply; overage consumes credits. |
| CloudWatch Logs | Ingestion/storage produced by Lambda | Small automatic logs may be Free Tier eligible; overage consumes credits. |

Pricing and Free Tier terms change. Check the AWS Billing console and the current Mumbai-region pricing before testing. Use only one to five PDFs initially; Textract bills by processed pages.

## Controls in this project

- No EC2, VPC, NAT Gateway, RDS, ECS/EKS, OpenSearch, provisioned concurrency, or continuous workers.
- Bucket is private, blocks all public access, and uses S3-managed encryption (SSE-S3).
- Lambda logs identifiers and status only; it never logs resume text.
- S3 only invokes Lambda for `incoming/*.pdf`.

## Cleanup

After testing, delete the CloudFormation application stack, empty the bucket, then delete the foundation stack. CloudFormation intentionally retains the bucket to avoid accidental resume deletion, so it must be emptied manually. Confirm that no `extracted/`, `failed/`, or `lambda-artifacts/` objects remain before deleting the foundation stack.
