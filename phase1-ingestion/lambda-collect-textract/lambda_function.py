import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

textract = boto3.client("textract")
s3 = boto3.client("s3")


def _put_json(prefix, job_id, payload):
    s3.put_object(Bucket=os.environ["RESULT_BUCKET"], Key=f"{prefix}/{job_id}.json",
                  Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                  ContentType="application/json", ServerSideEncryption="AES256")


def lambda_handler(event, context):
    for record in event.get("Records", []):
        try:
            message = json.loads(record["Sns"]["Message"])
            job_id = message["JobId"]
            status = message.get("Status")
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            print({"event": "sns_parse_failed", "error": type(error).__name__})
            raise
        source = {"bucket": message.get("DocumentLocation", {}).get("S3Bucket", ""),
                  "key": message.get("DocumentLocation", {}).get("S3ObjectName", "")}
        if status == "FAILED":
            _put_json("failed", job_id, {"job_id": job_id, "status": "FAILED", "source": source,
                                          "metadata": {"processed_at": datetime.now(timezone.utc).isoformat(), "pipeline_version": "phase1-v1"}})
            print({"event": "textract_failed", "job_id": job_id})
            continue
        if status != "SUCCEEDED":
            print({"event": "unexpected_textract_status", "job_id": job_id, "status": status})
            continue
        try:
            blocks, next_token, pages = [], None, 0
            while True:
                args = {"JobId": job_id}
                if next_token:
                    args["NextToken"] = next_token
                response = textract.get_document_text_detection(**args)
                blocks.extend(response.get("Blocks", []))
                pages = max(pages, response.get("DocumentMetadata", {}).get("Pages", 0))
                next_token = response.get("NextToken")
                if not next_token:
                    break
            text = "\n".join(block["Text"] for block in blocks if block.get("BlockType") == "LINE" and "Text" in block)
            _put_json("extracted", job_id, {"job_id": job_id, "status": "SUCCEEDED", "source": source,
                                              "page_count": pages, "text": text, "blocks": blocks,
                                              "metadata": {"processed_at": datetime.now(timezone.utc).isoformat(), "pipeline_version": "phase1-v1"}})
            print({"event": "textract_collected", "job_id": job_id, "block_count": len(blocks)})
        except ClientError as error:
            print({"event": "textract_collect_failed", "job_id": job_id, "error_code": error.response.get("Error", {}).get("Code", "Unknown")})
            raise
