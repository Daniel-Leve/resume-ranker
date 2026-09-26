# Infrastructure

`phase1.yaml` is a single CloudFormation template designed for deployment with the AWS CLI. It uses `CAPABILITY_NAMED_IAM` because IAM roles have stable, reviewable names. Its two Textract actions require `Resource: "*"` because those Textract APIs do not support resource-level IAM constraints. The start Lambda has `s3:GetObject` only for `incoming/*`, which Textract requires when validating the source PDF; all other S3, SNS, PassRole, and invocation permissions are scoped to this stack's resources.

Use `deploy.ps1` without `-Apply` for an authenticated CLI/template validation only. Use `-Apply` only after approving the cost review.
