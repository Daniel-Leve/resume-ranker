# SaaS API & Workers

This directory contains the AWS Serverless implementation of the Resume Screening pipeline.

It wraps the local CLI scripts (`phase2` and `phase3`) into asynchronous AWS Lambda workers and exposes a RESTful API.

## Directory Structure
*   `handlers/application_handler.py`: API Gateway REST entry points.
*   `workers/indexing_worker.py`: SQS consumer for Phase 2 indexing.
*   `workers/screening_worker.py`: SQS consumer for Phase 2+3 hybrid search & rerank.

## Deployment Instructions

This project is defined using the AWS Serverless Application Model (SAM) via the root `template.yaml`.

### Prerequisites
1. Install [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).
2. Ensure you have your `VOYAGE_API_KEY` and `MONGODB_URI`.
3. The root `requirements.txt` will be used by SAM to build dependencies for the Lambdas. If you are using Poetry, export it first:
   ```bash
   poetry export -f requirements.txt --output requirements.txt --without-hashes
   ```

### Build & Deploy
1. Build the application:
   ```bash
   sam build
   ```
2. Deploy to your AWS account:
   ```bash
   sam deploy --guided
   ```
   * During the guided deploy, you will be prompted for parameter overrides. Provide your `MongoDbUri` and `VoyageApiKey`.
   * **Note on ResumeBucketName:** Pass the exact name of the S3 bucket created in Phase 1. The SAM template will attach a new SQS event policy to this existing bucket.

## Local Testing
You can invoke the API locally using SAM:
```bash
sam local start-api --env-vars local-env.json
```
*(You will need to create a `local-env.json` containing the environment variables required by the Lambdas.)*
