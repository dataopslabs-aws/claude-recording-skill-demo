#!/usr/bin/env python3
"""
Run the full Lab 1 pipeline locally against a payload file: read the sheet, then fill the
form via AgentCore Browser. Same code path the deployed runtime executes.

    python local_run.py events/payload.example.json

Needs AWS creds + AgentCore access (it opens a real AgentCore Browser session).
"""

import json
import os
import sys

from runtime_handler import handler

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "events/payload.example.json"
    with open(path) as f:
        payload = json.load(f)
    # Optional safety cap: LIMIT=2 make run-local  -> only the first 2 rows are submitted.
    limit = os.environ.get("LIMIT")
    if limit:
        payload["limit"] = int(limit)
        print(f"[local] LIMIT={limit} — submitting only the first {limit} row(s)")
    summary = handler(payload)
    print(json.dumps(summary, indent=2, default=str))
