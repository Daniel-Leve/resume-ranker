import os
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

textract = boto3.client("textract")


def lambda_handler(event, context):
    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        bucket = s3.get("bucket", {}).get("name")
        key = urllib.parse.unquote_plus(s3.get("object", {}).get("key", ""))
        if not bucket or not key or not key.startswith("incoming/") or not key.lower().endswith(".pdf"):
            print("Rejected non-Phase-1 S3 event")
            continue
        try:
            response = textract.start_document_text_detection(
                DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
                NotificationChannel={
                    "SNSTopicArn": os.environ["SNS_TOPIC_ARN"],
                    "RoleArn": os.environ["TEXTRACT_SNS_ROLE_ARN"],
                },
            )
            print({"event": "textract_started", "bucket": bucket, "key": key,
                   "job_id": response["JobId"], "at": datetime.now(timezone.utc).isoformat()})
        except ClientError as error:
            print({"event": "textract_start_failed", "bucket": bucket, "key": key,
                   "error_code": error.response.get("Error", {}).get("Code", "Unknown")})
            raise
