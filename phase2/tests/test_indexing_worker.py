"""
Unit tests for api.workers.indexing_worker SQS handler logic and S3 key decoding.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from api.workers.indexing_worker import lambda_handler


class TestIndexingWorkerS3KeyDecoding:
    @patch("api.workers.indexing_worker._index_single")
    def test_s3_event_with_url_encoded_spaces_and_special_chars(self, mock_index):
        # In AWS S3 events, spaces become '+' or '%20'
        raw_s3_key = "extracted/john+doe%20resume%2Bspecial.json"
        expected_decoded_key = "extracted/john doe resume+special.json"

        event = {
            "Records": [
                {
                    "messageId": "msg-001",
                    "body": json.dumps({
                        "Records": [
                            {
                                "s3": {
                                    "object": {
                                        "key": raw_s3_key
                                    }
                                }
                            }
                        ]
                    })
                }
            ]
        }

        result = lambda_handler(event, None)
        assert result == {"batchItemFailures": []}
        mock_index.assert_called_once_with(expected_decoded_key)

    @patch("api.workers.indexing_worker._index_single")
    def test_direct_payload_is_not_double_decoded(self, mock_index):
        # Direct payload with a key containing a literal '+' must NOT be turned into a space
        direct_key = "extracted/c++_developer_resume.json"

        event = {
            "Records": [
                {
                    "messageId": "msg-002",
                    "body": json.dumps({
                        "s3_key": direct_key
                    })
                }
            ]
        }

        result = lambda_handler(event, None)
        assert result == {"batchItemFailures": []}
        mock_index.assert_called_once_with(direct_key)

    @patch("api.workers.indexing_worker._index_single", side_effect=RuntimeError("S3 read error"))
    def test_batch_item_failure_reporting(self, mock_index):
        event = {
            "Records": [
                {
                    "messageId": "msg-fail-123",
                    "body": json.dumps({
                        "s3_key": "extracted/corrupt.json"
                    })
                }
            ]
        }

        result = lambda_handler(event, None)
        assert result == {"batchItemFailures": [{"itemIdentifier": "msg-fail-123"}]}
