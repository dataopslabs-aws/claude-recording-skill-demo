#!/usr/bin/env python3
"""
Real AgentCore Browser smoke test — ONE row.

This is the test that could NOT run inside the Cowork sandbox (no network path to the
AgentCore data plane). Run it where AWS creds + AgentCore access exist — your laptop via
Claude Code, or CI:

    make browser-test          # or:  python test_agentcore_browser.py

It starts an AgentCore Browser session, fills a single test registration into the form
from events/payload.example.json, verifies the confirmation, and tears the session down.
Exit code 0 = PASS. The row uses obvious test data so it's easy to spot/delete in the
form responses.
"""

import json
import time

from params import Job
from form_filler import fill_form

# Unique email per run so the idempotency guard never treats a re-test as a duplicate.
_UNIQ = int(time.time())
TEST_ROW = {
    "email": f"agentcore.smoke.{_UNIQ}@example.com",
    "first": "AgentCore",
    "last": "Smoke",
    "emailid": f"agentcore.smoke.{_UNIQ}@example.com",
    "phone": "9000000000",
    "food": "Vegan",
    "size": "M",
    "time": "8:00 AM - 12:00 PM",
}

if __name__ == "__main__":
    payload = json.load(open("events/payload.example.json"))
    job = Job.from_payload(payload)
    print(f"[smoke] AgentCore Browser fill of form {job.form.public_id} "
          f"in {job.region} ...")
    results = fill_form([TEST_ROW], job.form, region=job.region)
    print(json.dumps(results, indent=2))
    ok = bool(results) and results[0]["ok"]
    print("AgentCore Browser smoke test:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)
