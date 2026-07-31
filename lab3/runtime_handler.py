"""
AgentCore Runtime entrypoint for Lab 1.

EventBridge (the daily schedule) invokes this runtime with the {sheet, form} payload.
The handler parses it into a Job and runs the deterministic pipeline: read the sheet ->
fill the form (AgentCore Browser, POST fallback) -> return a summary. The ADK v2 agent
(agent.py) wraps the same steps as graph nodes and adds exception triage / HITL; use
whichever entrypoint you deploy.

Deploy this module as the AgentCore Runtime container entrypoint. Credentials come from
the runtime's execution role — nothing secret is read from the payload.
"""

from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from params import Job
from sheet_reader import read_rows
from form_filler import fill_form

app = BedrockAgentCoreApp()


@app.entrypoint
def handler(payload: dict, context=None) -> dict:
    job = Job.from_payload(payload)          # {sheet, form} -> typed job
    rows = read_rows(job.sheet)              # variable #1: the sheet
    if job.limit:                            # optional safety cap for test runs
        rows = rows[:job.limit]
    results = fill_form(rows, job.form, region=job.region)  # variable #2: the form

    submitted = sum(1 for r in results if r["ok"] and r["via"] == "ui")
    duplicates = sum(1 for r in results if r["via"] == "duplicate")
    summary = {
        "form": job.form.public_id,
        "sheet": job.sheet.id,
        "total": len(results),
        "submitted": submitted,           # newly submitted this run
        "duplicates": duplicates,         # skipped (already recorded)
        "failed": [r for r in results if not r["ok"]],
    }
    print(f"[lab3] form {job.form.public_id}: {submitted} new, "
          f"{duplicates} duplicate, {len(summary['failed'])} failed")
    return summary


if __name__ == "__main__":
    app.run()
