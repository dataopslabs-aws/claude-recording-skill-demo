"""
ADK v2 agent for Lab 1 — the composable, graph form of the pipeline.

ADK 2.0 is a graph engine: Agents, Tools and Functions are nodes in a workflow graph.
Lab 1 is a 3-node graph with an optional human-in-the-loop (HITL) gate before the
side-effecting submit:

        read_sheet ──▶ [HITL: confirm rows] ──▶ fill_form ──▶ verify

The three steps are the same functions used by runtime_handler.py, exposed here as tools
so the agent can also do exception triage (e.g. a row that fails both UI and POST) rather
than silently dropping it. The deterministic happy path needs no LLM; the agent earns its
place only on ambiguity/exceptions — keep the model out of the per-row loop for cost/audit.

NOTE: exact ADK 2.0 Python class/decorator names evolve — confirm against adk.dev for your
installed version. The tool functions and the graph shape below are the stable part.
"""

from __future__ import annotations

from params import Job
from sheet_reader import read_rows
from form_filler import fill_form

# --- ADK v2 imports (verify names for your ADK version) --------------------------
# from google.adk.agents import Agent
# from google.adk.workflow import Graph, node, HumanInLoop
# from google.adk.tools import tool


# --- Nodes / tools ---------------------------------------------------------------
def read_sheet_tool(payload: dict) -> dict:
    """Node 1 — read the sheet named in the payload. Returns rows + a count to confirm."""
    job = Job.from_payload(payload)
    rows = read_rows(job.sheet)
    return {"rows": rows, "count": len(rows), "job": payload}


def fill_form_tool(rows: list[dict], payload: dict) -> dict:
    """Node 2 — fill the form (AgentCore Browser, POST fallback). Side-effecting."""
    job = Job.from_payload(payload)
    results = fill_form(rows, job.form, region=job.region)
    return {"results": results,
            "submitted": sum(1 for r in results if r["ok"]),
            "failed": [r for r in results if not r["ok"]]}


def verify_tool(results: list[dict]) -> dict:
    """Node 3 — summarize; flag rows that need manual attention."""
    return {"total": len(results),
            "submitted": sum(1 for r in results if r["ok"]),
            "needs_attention": [r for r in results if not r["ok"]]}


# --- Graph wiring (reference; adapt to your ADK 2.0 API) -------------------------
def build_graph():
    """
    Pseudocode for the ADK 2.0 workflow graph:

        g = Graph("lab3-form-fill")
        n_read   = g.add(node(read_sheet_tool))
        n_gate   = g.add(HumanInLoop(prompt="Confirm N rows before submitting"))
        n_fill   = g.add(node(fill_form_tool))
        n_verify = g.add(node(verify_tool))
        g.edge(n_read, n_gate).edge(n_gate, n_fill).edge(n_fill, n_verify)
        return g

    In unattended mode (the daily schedule) the HITL gate is configured to auto-approve
    with a row-count guard; for interactive runs it pauses for confirmation.
    """
    raise NotImplementedError("Wire to your installed ADK 2.0 graph API — see docstring.")


def run(payload: dict) -> dict:
    """Deterministic driver equivalent to the graph's happy path (no LLM in the loop)."""
    read = read_sheet_tool(payload)
    filled = fill_form_tool(read["rows"], payload)
    return verify_tool(filled["results"])
