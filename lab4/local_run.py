#!/usr/bin/env python3
"""
Run the full Lab 4 pipeline locally against a payload file: read the sheet, then hybrid-fill
the form (deterministic Playwright + Nova Act menu). Uses the deterministic core directly
(no Strands agent), so it's cheap and needs no Bedrock model access — just AWS creds for the
AgentCore Browser + DynamoDB.

    python local_run.py events/payload.example.json
    LIMIT=2 python local_run.py            # cap to the first 2 rows
"""

import json
import os
import sys

from app import run_pipeline

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "events/payload.example.json"
    with open(path) as f:
        payload = json.load(f)
    limit = os.environ.get("LIMIT")
    if limit:
        payload["limit"] = int(limit)
        print(f"[local] LIMIT={limit} — submitting only the first {limit} row(s)")
    print(json.dumps(run_pipeline(payload), indent=2, default=str))
