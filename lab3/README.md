# Lab 3 — Ship the skill as a runnable, scheduled AgentCore stack

Lab 1 taught the skill from a screen recording; Lab 2 added DynamoDB reconciliation.
**Lab 3 turns Lab 1's `event-registration-form-fill` skill into a deployed, scheduled,
idempotent automation on AWS** — the same outcome (sheet rows → Google Form responses),
now running unattended on Amazon Bedrock AgentCore with a real browser, safe to run every
day.

The whole thing is driven by **one payload** — the Google Sheet to read and the Google
Form to fill — so retargeting is a config change, not a code change.

![Lab 3 architecture — EventBridge → Lambda → AgentCore Runtime → AgentCore Browser → DynamoDB, deterministic](./assets/lab3-architecture.png)

---

## Is there an LLM? Is it the AgentCore Browser Tool?

Three things enterprise review usually asks first:

- **LLM involved? No — zero.** There is no model inference anywhere in the execution path:
  no Bedrock model call, no Nova Act, no natural-language step. Every decision is fixed
  Python logic, static dictionaries, and CSS/ARIA selectors. Fully deterministic *logic*
  (the live web page and network are the only non-deterministic factors, which is why
  there are explicit timeouts and per-row error handling).
- **AgentCore Browser Tool? Yes — exclusively.** Submissions go through a real AgentCore
  Browser session driven by Playwright over CDP. CloudWatch confirms both planes:
  `StartBrowserSession` then a Playwright connection to
  `wss://bedrock-agentcore.../browser-streams/aws.browser.v1/sessions/<id>/automation`.
  The AgentCore Browser *can* be steered by an LLM (Nova Act) — **we deliberately don't**;
  we use it as a managed, isolated, remote Chromium that deterministic Playwright controls.
- **API fallback? No.** The old `formResponse` HTTP POST path was removed. Every submit
  goes through the rendered UI. (The one `formResponse` string in the code reads the
  success *URL* after a UI submit; it is not an HTTP call.)

---

## Architecture

```
EventBridge Scheduler   cron(0 5 * * ? *)   Input = { sheet, form, region }
        │
        ▼
lab3-form-fill-forwarder  (Lambda)          deploy/lambda_forwarder.py
        │  bedrock-agentcore:InvokeAgentRuntime(payload)
        ▼
AgentCore Runtime  (container)              runtime_handler.py  ← entrypoint
        │
        ├─ params.py         parse { sheet, form, region, limit }
        ├─ sheet_reader.py   GET /export?format=csv  → rows (ALL rows; not gviz)
        └─ form_filler.py    AgentCore Browser + Playwright
                 ├─ BrowserClient.start()           → AgentCore Browser session
                 ├─ connect_over_cdp(ws, headers)   → attach Playwright
                 ├─ idempotency.reserve()  ── DynamoDB conditional put ──┐
                 │      exists → skip (duplicate)                        │
                 │      new    → fill UI → submit → confirm              │
                 └─ client.stop()                                       │
                                                                        ▼
                                              lab3-form-fill-dedup (DynamoDB)
```

**No LLM. AgentCore Browser Tool only. No API fallback.**

---

## Flow walkthrough (call chain)

```
runtime_handler.handler(payload)
  1. Job.from_payload(payload)              params.py  → typed { sheet, form, region, limit }
  2. read_rows(job.sheet)                   sheet_reader.py
        urllib GET /export?format=csv       full export (gviz stops at blank rows — avoided)
        csv.DictReader → HEADER_MAP         → list[dict] keyed first/last/email/…
        HTML-guard raises if not CSV        (sheet must be link-viewable, or use Sheets API)
  3. rows = rows[:limit]  if limit
  4. fill_form(rows, job.form, region)      form_filler.py
        a. BrowserClient(region).start()          → StartBrowserSession (recording ON)
        b. client.generate_ws_headers()           → signed CDP ws url + auth headers
        c. pw.chromium.connect_over_cdp(...)      → attach to the remote browser
        d. per row (sheet order):
             email = row.email or row.emailid
             reserve(form_id, email)              idempotency.py → DynamoDB conditional put
               ├─ exists → {via:"duplicate"}, skip        ← existing rows never re-submitted
               └─ new    → fill_row_ui():
                     validate_options()            static allowed-value sets, fail loud
                     page.goto(viewform_url)
                     fill_email / fill_text        get_by_role("textbox")
                     choose_radio / choose_checkbox get_by_role("radio"/"checkbox", name=…)
                     click_submit()                get_by_role("button", name=/submit/i)
                     is_confirmed()                URL has "formResponse" / "recorded"
                 if not confirmed → release()      DynamoDB delete → retry next run
        e. client.stop()                          → StopBrowserSession
  5. summary { submitted (new via ui), duplicates, failed }  → returned to the Lambda
```

---

## The one payload (composability seam)

`events/payload.example.json`, validated by `events/payload.schema.json`:

```json
{ "sheet": { "id": "<SHEET_ID>", "gid": "<GID>" },
  "form":  { "public_id": "<FORM_PUBLIC_ID>" },
  "region": "us-east-1" }
```

`params.Job.from_payload()` turns it into a typed job. No sheet/form id is hardcoded in any
pipeline module — retarget by changing the payload (the EventBridge schedule's Input), or
add `"limit": N` for a capped test run.

---

## Files

| File | Role | LLM? |
|------|------|------|
| `runtime_handler.py` | AgentCore Runtime entrypoint: parse → read → fill → summarize | no |
| `params.py` | payload contract → `Job` (the seam) | no |
| `sheet_reader.py` | read all rows from the sheet's CSV export | no |
| `form_filler.py` | AgentCore Browser + Playwright fill, idempotent, no fallback | no |
| `idempotency.py` | DynamoDB conditional put / delete (dedup) | no |
| `agent.py` | optional ADK v2 graph form (reference; **not** deployed) | no* |
| `local_run.py` · `test_agentcore_browser.py` | local full-run / one-row browser smoke test | no |
| `Dockerfile` · `requirements.txt` · `Makefile` | container + one-command flows | — |
| `events/` | payload schema + example | — |
| `deploy/` | Lambda forwarder, schedule, dedup table, IAM, ship guide | — |
| `infra/eventbridge-schedule.md` | schedule + payload delivery details | — |

`*` `agent.py` is LLM-free today; only if you deploy it as the entrypoint **and** attach a
model node for exception triage would an LLM enter — the deployed entrypoint is
`runtime_handler.py`.

---

## Run it / ship it

Everything runs in a `.venv` built with **python3.12** (override with
`make install PYTHON=/path/to/python3.12`). Your **AWS account is auto-detected** from your
credentials — no account number to edit anywhere. Needs an AgentCore-enabled account.

```bash
cd lab3
make whoami          # confirm the detected ACCOUNT + REGION
make install         # .venv (python3.12) + deps + chromium
make doctor          # check interpreter, deps, AWS creds
make dedup-table     # create the DynamoDB idempotency table
make browser-test    # REAL AgentCore Browser test: one unique row, start→fill→verify
make run-local LIMIT=2   # full pipeline (read sheet → fill form), capped to 2 rows
make deploy          # register the AgentCore runtime (agentcore configure + launch)
make runtime-policy  # grant the runtime role browser + dynamodb perms (REQUIRED)
make invoke          # fire the deployed runtime once
make deploy-lambda   # forwarder Lambda + role
make schedule TIMEZONE=Asia/Kolkata   # daily 05:00 in your zone
```

**Step-by-step workshop guide: [`../ImplementationPlan.md`](../ImplementationPlan.md).**
Quick command reference + IAM: `deploy/README.md`. Schedule details:
`infra/eventbridge-schedule.md`. Plain-English Playwright walkthrough (code ↔ what a human
does): [`WALKTHROUGH.md`](./WALKTHROUGH.md).

---

## Resources this creates (in *your* account)

Account and region come from your credentials (`REGION` defaults to `us-east-1`). Names are
Makefile variables — defaults shown:

| Resource | Default name | Created by |
|----------|--------------|------------|
| AgentCore Runtime | `lab3_form_fill` | `make deploy` |
| Runtime role inline policy | `lab3-runtime` (`bedrock-agentcore:*Browser*`, `dynamodb:*Item`, ssm/kms/logs) | `make runtime-policy` |
| Dedup table (DynamoDB) | `lab3-form-fill-dedup` | `make dedup-table` |
| Forwarder Lambda + role | `lab3-form-fill-forwarder` / `lab3-lambda-forwarder` | `make deploy-lambda` |
| Schedule + role (EventBridge) | `lab3-form-fill-daily` (05:00) / `lab3-scheduler-invoke` | `make schedule` |

The IAM templates in `deploy/*.json` use `__ACCOUNT_ID__` / `__REGION__` placeholders that
the deploy scripts substitute at apply time — so there are no hardcoded account numbers.

Verified end-to-end (an earlier build under `lab1_*` names) returned
`{"submitted": 11, "duplicates": 11, "failed": []}` after the dedup table was seeded with
the already-submitted rows — the idempotency guard skipped the 11 existing and submitted
only the new ones.

---

## Operational notes & gotchas (learned the hard way)

- **Read the full sheet, not gviz.** The gviz CSV endpoint (`/gviz/tq?tqx=out:csv`) stops
  at the first blank row and silently drops everything below a gap. Use
  `/export?format=csv` (what `sheet_reader.py` does). The sheet must be link-viewable, or
  swap in the Sheets-API + service-account path in `sheet_reader.py`.
- **Two IAM gates for the browser.** The runtime execution role needs
  `bedrock-agentcore:StartBrowserSession` **and** access to the automation stream — granted
  together via `bedrock-agentcore:*Browser*`. The toolkit's auto-created role does NOT
  include these, so the first invoke fails `AccessDeniedException` until you run
  `make runtime-policy` (which finds the role and attaches `deploy/iam_runtime_policy.json`
  with your account/region substituted in).
- **Idempotency semantics.** Key = `"<form_public_id>#<email_lowercased>"`. Reserve is a
  conditional `PutItem` (only succeeds if new); a failed submit calls `release()` so the row
  retries next run. This also makes the pipeline safe against EventBridge at-least-once
  re-delivery. When adopting on a form that already has responses, **seed the table** with
  the already-submitted emails so they aren't re-sent.
- **Set the schedule timezone.** `cron(0 5 * * ? *)` defaults to UTC; pass `TIMEZONE=`.
- **Toolkit deprecation.** `bedrock-agentcore-starter-toolkit` still works but AWS now
  points to the `@aws/agentcore` CLI (`npm i -g @aws/agentcore`); migrate the `deploy` /
  `invoke` targets when convenient.
