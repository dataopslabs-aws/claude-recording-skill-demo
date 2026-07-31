# Implementation Plan — Deploy the Form-Fill Automation (Lab 3)

A step-by-step, copy-paste guide to take **Skill 1** (`event-registration-form-fill`) from
an interactive Cowork run to a **deployed, scheduled, idempotent** automation on AWS. Built
for the monthly workshop — a participant with an AWS account should get to a working daily
job in about **45–60 minutes**.

- **What it does:** reads rows from a Google Sheet and submits each as one response to a
  Google Form, every morning, automatically.
- **How:** a fully **deterministic** AWS Bedrock **AgentCore Runtime** job that fills the
  form through the **AgentCore Browser Tool** (real headless Chromium driven by Playwright)
  — **no LLM, no API fallback**. Idempotent via DynamoDB; triggered by EventBridge.
- **The only thing you change per form is one payload:** `{ sheet, form }`.

> Your **AWS account number is auto-detected** from your credentials. There is nothing to
> hardcode — the IAM templates use `__ACCOUNT_ID__` / `__REGION__` placeholders that the
> deploy scripts substitute at apply time.

---

## Architecture (what you're building)

```
EventBridge Scheduler   cron(0 5 * * ? *)   Input = { sheet, form, region }
        │
        ▼
lab3-form-fill-forwarder  (Lambda)          → InvokeAgentRuntime(payload)
        │
        ▼
AgentCore Runtime  lab3_form_fill            runtime_handler.py
        ├─ read sheet   (CSV export → rows)
        └─ fill form    (AgentCore Browser + Playwright, deterministic)
                 └─ DynamoDB dedup: skip anything already submitted
```

---

## Prerequisites (check these first)

**On your laptop:**
- [ ] **AWS CLI v2** configured (`aws sts get-caller-identity` returns your account)
- [ ] **Docker** running (used by `agentcore launch` to build the container)
- [ ] **Python 3.12** (`python3.12 --version`). macOS: `brew install python@3.12`
- [ ] **Node.js** (only if you later switch to the `@aws/agentcore` CLI)
- [ ] `git` and this repo cloned

**In AWS (the account your CLI points at):**
- [ ] **Bedrock AgentCore is enabled** in your region (default `us-east-1`)
- [ ] IAM permissions to: create/invoke AgentCore runtimes, create IAM roles + inline
      policies, create Lambda functions, create EventBridge schedules, create a DynamoDB
      table, read CloudWatch logs

**A Google Form + Sheet you own** (see Part A):
- [ ] A Google **Form** that collects the fields you want
- [ ] A Google **Sheet** with one row per submission, **shared "Anyone with the link →
      Viewer"** (so the runtime can read it without Google credentials)

**Cost:** a few cents. AgentCore Browser is pay-per-session, Lambda + DynamoDB + EventBridge
are effectively free at this volume. Remember to run **Teardown** (last section) after the
workshop.

---

## Part A — Prepare your Form and Sheet (10 min)

The reference form has these fields; keep the same shape or edit the field maps in
`lab3/form_filler.py` (`QUESTION` / `OPTIONS`) and `lab3/sheet_reader.py` (`HEADER_MAP`).

| Sheet column | Form question | Type | Allowed values |
|--------------|---------------|------|----------------|
| Email | Email (collected) | email | — |
| First Name | First Name | text | — |
| Last Name | Last Name | text | — |
| Email ID | Email ID | text | — |
| Phone Number | Phone Number | text | 10 digits |
| Preferred Food | Preferred Food | checkbox | Vegetarian, Non-Vegetarian, Vegan, Gluten-Free |
| T-Shirt Size | T-Shirt Size | radio | XS, S, M, L, XL, XXL |
| Event Attendance Time | Event Attendance Time | radio | 8:00 AM - 12:00 PM, 1:00 PM - 4:00 PM |

**Get the two IDs:**
- **Form public id** — open the form's **Send → link** (a `forms.gle/...` or
  `/forms/d/e/<FORM_PUBLIC_ID>/viewform` URL). You want the `1FAIpQL...` part.
- **Sheet id + gid** — from the sheet URL:
  `docs.google.com/spreadsheets/d/<SHEET_ID>/edit?gid=<GID>`.

**Form settings that matter:**
- Turn **OFF** "Limit to 1 response" and "collect **verified** emails" — either forces
  Google sign-in and breaks unattended runs.
- Set the sheet share to **Anyone with the link → Viewer** (or use the Sheets-API +
  service-account path noted in `lab3/sheet_reader.py`).

**Put your IDs in the payload** — edit `lab3/events/payload.example.json`:

```json
{ "sheet": { "id": "<YOUR_SHEET_ID>", "gid": "<YOUR_GID>" },
  "form":  { "public_id": "<YOUR_FORM_PUBLIC_ID>" },
  "region": "us-east-1" }
```

---

## Part B — Local setup & validation (10 min)

```bash
cd lab3
make whoami          # prints the detected ACCOUNT + REGION — sanity-check them
make install         # builds .venv with python3.12, installs deps + chromium
make doctor          # confirms interpreter, deps, and AWS creds (prints your caller ARN)
```

If `python3.12` isn't on PATH: `make install PYTHON=/opt/homebrew/bin/python3.12`.

Create the dedup table, then validate the browser path and the sheet→form path with a small
capped run:

```bash
make dedup-table         # DynamoDB table lab3-form-fill-dedup
make browser-test        # one unique test row through a REAL AgentCore Browser session
make run-local LIMIT=2   # reads your sheet, fills the first 2 rows
```

Expected: `browser-test` ends `PASS`; `run-local` prints
`{"submitted": 2, "duplicates": 0, "failed": []}` and two responses appear in your form.

> `run-local` runs the **exact same code** the cloud runtime runs — if it works here, the
> deploy will behave identically.

---

## Part C — Deploy to AWS (15 min)

```bash
make deploy            # agentcore configure + launch: builds image, pushes to ECR, registers runtime
make runtime-policy    # REQUIRED: grants the runtime role AgentCore Browser + DynamoDB perms
make invoke            # fire the runtime once in the cloud with your payload
```

**Why `make runtime-policy` is not optional:** `agentcore launch` auto-creates an execution
role that can run the container but **cannot start a browser session**. Without this step
the first `make invoke` fails `AccessDeniedException: ...StartBrowserSession`. The target
finds the auto-created role and attaches the browser + dynamodb policy (account/region
substituted in). If you deployed before running it, just run it and `make invoke` again.

A successful invoke returns, e.g.:

```json
{ "submitted": 9, "duplicates": 2, "failed": [] }
```

`submitted` = new rows filled this run, `duplicates` = rows already recorded (skipped),
`failed` = rows needing attention.

---

## Part D — Schedule the daily run (5 min)

```bash
make deploy-lambda                    # forwarder Lambda + its role
make schedule TIMEZONE=Asia/Kolkata   # daily 05:00 in YOUR timezone (default is NOT UTC-safe)
```

`make schedule` also creates the `lab3-scheduler-invoke` role and points the schedule's
Input at `events/payload.example.json`. To **retarget** later, edit that file (or the
schedule's Input) and re-run `make schedule` — no code change, no redeploy.

**Trigger it once now (optional dry-run of the 05:00 job):**

```bash
aws lambda invoke --function-name lab3-form-fill-forwarder \
  --cli-binary-format raw-in-base64-out \
  --payload file://events/payload.example.json /dev/stdout
```

---

## Part E — Verify

- **Form responses:** the new rows appear; already-submitted rows are not duplicated.
- **Runtime logs (CloudWatch):**
  ```bash
  aws logs tail /aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT --since 15m
  ```
  (`make deploy`/`make invoke` print the exact log command and runtime id.)
- **Dedup table grows** by the number of newly-submitted rows:
  ```bash
  aws dynamodb scan --table-name lab3-form-fill-dedup --select COUNT
  ```
- **Schedule exists:** `aws scheduler get-schedule --name lab3-form-fill-daily`.

---

## Troubleshooting (the errors you're most likely to hit)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `make: python: No such file or directory` | system has no `python` | the Makefile uses the venv; run `make install` first (uses `python3.12`) |
| `AccessDeniedException ... StartBrowserSession` | runtime role lacks browser perms | `make runtime-policy`, then `make invoke` |
| `403 ... not authorized to access automation stream` | browser perms too narrow | already covered by `bedrock-agentcore:*Browser*` in `make runtime-policy`; ensure it ran |
| Runtime submits fewer rows than expected | sheet read used a truncating endpoint | Lab 3 uses `/export?format=csv` (all rows). If you customized it, don't use gviz — it stops at the first blank row |
| `The execution role you provide must allow AWS EventBridge Scheduler to assume the role` | scheduler role missing/propagating | re-run `make schedule` (it creates the role); wait ~15s and retry |
| Sheet read raises "did not return CSV (got HTML)" | sheet isn't link-viewable | share the sheet "Anyone with the link → Viewer", or use the Sheets-API path |
| A row is `failed` with "not an allowed option" | sheet value ≠ a form option | fix the sheet cell; the row retries next run (its dedup marker was released) |
| Toolkit prints "no longer supported" | starter toolkit deprecation notice | harmless; migrate to `@aws/agentcore` when convenient (`npm i -g @aws/agentcore`) |

---

## Teardown (run after the workshop)

```bash
cd lab3
aws scheduler delete-schedule --name lab3-form-fill-daily
aws lambda delete-function    --function-name lab3-form-fill-forwarder
aws dynamodb delete-table     --table-name lab3-form-fill-dedup
# delete the runtime (get its id from: aws bedrock-agentcore-control list-agent-runtimes)
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id <lab3_form_fill-id>
# roles (detach/delete when done):
for r in lab3-scheduler-invoke lab3-lambda-forwarder; do
  aws iam delete-role-policy --role-name "$r" --policy-name invoke 2>/dev/null || true
  aws iam delete-role       --role-name "$r" 2>/dev/null || true
done
make clean   # remove the local .venv
```

---

## Appendix — knobs & reference

**Override any default** on the make command line:

```bash
make deploy   RUNTIME=myteam_form_fill
make schedule TIMEZONE=Europe/London REGION=eu-west-1
make run-local LIMIT=5 PAYLOAD=events/other.json
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `REGION` | `us-east-1` | AWS region |
| `ACCOUNT` | *auto (STS)* | AWS account id — auto-detected |
| `RUNTIME` | `lab3_form_fill` | AgentCore runtime name |
| `LAMBDA` | `lab3-form-fill-forwarder` | forwarder function name |
| `DEDUP_TABLE` | `lab3-form-fill-dedup` | DynamoDB table |
| `TIMEZONE` | `America/Los_Angeles` | schedule timezone (**set yours**) |
| `LIMIT` | *(unset)* | cap rows for a test run |
| `PYTHON` | `python3.12` | interpreter used to build the venv |

**Is there an LLM?** No — the execution path is fully deterministic (fixed selectors, static
maps, DynamoDB conditional writes). **Is it the AgentCore Browser Tool?** Yes, exclusively —
no HTTP/API fallback. See `lab3/README.md` for the full code + flow analysis.
