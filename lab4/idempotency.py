"""
DynamoDB-backed idempotency for Skill 1 — never submit the same (form, email) twice.

Reserve-before-submit with rollback:
  * reserve() does a conditional PutItem that only succeeds if the key is new.
  * If the browser submit later fails, release() deletes the marker so the row can be
    retried on the next run.
  * An already-present key (a row submitted on an earlier run) makes reserve() return
    False, and the caller skips it.

This also makes the pipeline safe against EventBridge at-least-once re-delivery: only one
invocation can win the conditional put for a given key.

Table: DEDUP_TABLE env or default 'lab4-form-fill-dedup', partition key 'pk' (String).
"""

import os
import time

import boto3
from botocore.exceptions import ClientError

TABLE = os.environ.get("DEDUP_TABLE", "lab4-form-fill-dedup")
_table = boto3.resource("dynamodb").Table(TABLE)


def key(form_id: str, email: str) -> str:
    return f"{form_id}#{(email or '').strip().lower()}"


def reserve(form_id: str, email: str) -> bool:
    """True if new (now reserved); False if this (form,email) was already recorded."""
    try:
        _table.put_item(
            Item={"pk": key(form_id, email), "ts": int(time.time())},
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ConditionalCheckFailedException":
            return False
        if code == "ResourceNotFoundException":
            raise RuntimeError(
                f"Dedup table '{TABLE}' not found — create it "
                f"(make dedup-table) or set DEDUP_TABLE.") from e
        raise


def release(form_id: str, email: str) -> None:
    """Undo a reservation so a failed row can retry on the next run."""
    _table.delete_item(Key={"pk": key(form_id, email)})
