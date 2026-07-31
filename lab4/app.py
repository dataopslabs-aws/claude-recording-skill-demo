"""
Lab 4 — unified AgentCore Runtime entrypoint. Deploy THIS one file.

It runs the hybrid pipeline: deterministic Playwright for the known fields, Nova Act for
the Menu Option (with a dietary guardrail), idempotent via DynamoDB.

Two modes, chosen per invocation via the payload "mode" (or the MODE env var default):
  * "agent" (default): a Strands agent orchestrates the run and returns a written report.
  * "deterministic": run the pipeline directly, no LLM in the control flow.
Same result either way; "agent" adds ONE Bedrock reasoning call per run (not per row).

    make deploy                         # agentcore configure --entrypoint app.py && launch
    # switch mode without redeploying:  payload {"mode": "deterministic"}

Verify strands-agents (Agent / tool / BedrockModel) and MODEL_ID against your installed
versions — those are the version-sensitive spots. The runtime role needs
bedrock:InvokeModel (already granted for Nova Act + the Strands model).
"""

from __future__ import annotations

import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel

from params import Job
from sheet_reader import read_rows
from form_filler import fill_form

app = BedrockAgentCoreApp()

_CTX: dict = {}                                    # per-invocation context for the tool
DEFAULT_MODE = os.environ.get("MODE", "agent")
# Amazon Nova Pro — available on this account with no marketplace agreement (works now).
# Switch to "us.anthropic.claude-opus-4-5-20251101-v1:0" once Bedrock model access +
# a valid payment instrument are set up. Override with the MODEL_ID env var.
MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-pro-v1:0")


def run_pipeline(payload: dict) -> dict:
    """Deterministic core: read the sheet, hybrid-fill every row, return a summary.
    (Deterministic Playwright + Nova Act menu + guardrail + idempotency live in fill_form.)"""
    job = Job.from_payload(payload)
    rows = read_rows(job.sheet)
    if job.limit:
        rows = rows[:job.limit]
    results = fill_form(rows, job.form, region=job.region)
    return {
        "form": job.form.public_id,
        "sheet": job.sheet.id,
        "total": len(results),
        "submitted": sum(1 for r in results if r["ok"] and r["via"] == "hybrid"),
        "duplicates": sum(1 for r in results if r["via"] == "duplicate"),
        "menu_picks": [{"email": r["email"], "menu": r.get("menu", "")}
                       for r in results if r["ok"] and r.get("menu")],
        "failed": [r for r in results if not r["ok"]],
    }


@tool
def process_registrations() -> dict:
    """Read the sheet and fill every registration (deterministic fields + Nova Act menu,
    with the dietary guardrail and idempotency). Returns submitted / duplicate / failed
    counts and the menu items chosen."""
    _CTX["summary"] = run_pipeline(_CTX["payload"])
    return _CTX["summary"]


SYSTEM = (
    "You process daily event registrations. Call process_registrations, then report in one "
    "short paragraph: how many were newly submitted, how many skipped as duplicates, which "
    "menu items were chosen for whom, and flag any failed or guardrail-blocked rows for "
    "manual follow-up. Never invent numbers — use the tool output."
)

_agent = Agent(model=BedrockModel(model_id=MODEL_ID),
               tools=[process_registrations], system_prompt=SYSTEM)


@app.entrypoint
def handler(payload: dict, context=None) -> dict:
    """AgentCore Runtime entrypoint. EventBridge delivers the {sheet, form} payload."""
    _CTX.clear()
    _CTX["payload"] = payload
    mode = str(payload.get("mode") or DEFAULT_MODE).lower()
    if mode == "deterministic":
        return {"mode": "deterministic", "summary": run_pipeline(payload)}
    result = _agent("Process today's registrations and report the outcome.")
    return {"mode": "agent", "report": str(result), "summary": _CTX.get("summary")}


if __name__ == "__main__":
    app.run()
