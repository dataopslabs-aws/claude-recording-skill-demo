# Lab 4 — Detailed Workflow (`workflow_info.md`)

A presenter's guide to how Lab 4 works end to end. Lab 4 fills a Google Form from a Google
Sheet, but the form now has a **Food Option** question that has *no matching sheet column* —
the right dish must be **reasoned** from each attendee's dietary preference. So Lab 4 is a
**hybrid**: deterministic code for the fields it knows, an LLM (Amazon Nova Act) for the one
field that needs judgment, a deterministic **guardrail** to keep the LLM honest, and an
optional **Strands agent** to orchestrate the whole run inside AWS Bedrock AgentCore.

---

## 1. The one-sentence story

> Deterministic Playwright fills the known fields, **Nova Act** reads the live menu and
> picks the dish that fits each attendee's diet, a **guardrail** checks the pick isn't
> unsafe, a **Strands agent** orchestrates and reports, and **DynamoDB** makes sure nobody
> is submitted twice — all running on **AgentCore Runtime + AgentCore Browser**.

---

## 2. Three "brains", each used where it's strong

| Brain | Does | Why it's the right tool here |
|-------|------|------------------------------|
| **Deterministic Playwright** | fills Email, First/Last, Email ID, Phone, Preferred Food, T‑Shirt Size, Attendance Time | fields are known and stable → cheap, fast, 100% reproducible |
| **Nova Act (LLM)** | picks the **Food Option** dish from the attendee's diet | no sheet column; the menu can change → needs reasoning, not a lookup |
| **Strands agent (LLM)** | orchestrates: read → fill → report | optional; adds reasoning/reporting over the run (not per row) |
| **Deterministic guardrail** | validates Nova Act's dish pick | safety floor: an LLM can be confidently wrong (e.g. "burrito is gluten‑free") |

Core principle running through all four labs: **LLM for judgment, deterministic code for
everything measurable and for the safety net.**

---

## 3. Architecture

```
EventBridge Scheduler  cron(0 5 * * ? *)   Input = { sheet, form, region, mode }
        │
        ▼
lab4-form-fill-forwarder  (Lambda)  ──►  InvokeAgentRuntime(payload)
        │
        ▼
AgentCore Runtime  lab4_form_fill   ── entrypoint: app.py ──┐
        │                                                   │
        │  mode = "agent"        mode = "deterministic"     │
        ▼                              ▼                     │
  Strands agent (Nova Pro)        run_pipeline() ───────────┤
   └─ tool: process_registrations ─────────────────────────┘
                                    │
                                    ▼
                    read_rows(sheet)  ──►  fill_form(rows, form)
                                                 │
                          ┌──────────────────────┴───────────────────────┐
                          ▼                                               ▼
                AgentCore Browser (one session)                   DynamoDB dedup
                  ├─ Playwright: known fields                     (skip already-submitted)
                  └─ Nova Act: Food Option  ──► guardrail
```

Everything variable is one payload: **`{ sheet, form }`** (+ optional `region`, `mode`,
`limit`).

---

## 4. Files and their jobs

| File | Role |
|------|------|
| `app.py` | **the single entrypoint you deploy.** Chooses mode (agent/deterministic), builds the Strands agent, runs the pipeline. |
| `params.py` | turns the payload into a typed `Job` (sheet id/gid, form public id, region, limit). |
| `sheet_reader.py` | reads all rows from the sheet's CSV **export** (not gviz — gviz stops at blank rows). |
| `form_filler.py` | opens one AgentCore Browser session via Nova Act; `_fill_known` (Playwright) + the Nova Act menu step + submit + dedup. |
| `menu_picker.py` | the Nova Act call that picks the Food Option + the dietary **guardrail** (`GUARDRAIL=off/warn/strict`). |
| `idempotency.py` | DynamoDB conditional writes: reserve-before-submit, release-on-failure. |
| `deploy/` | forwarder Lambda, schedule, dedup table, Nova Act workflow definition, IAM. |
| `Makefile` | one-command flows (install, deploy, invoke, schedule, …). |

---

## 5. End-to-end workflow (what actually happens)

### 5.1 Trigger
- **Scheduled:** EventBridge fires daily at 05:00 with the `{ sheet, form }` payload → the
  **forwarder Lambda** → `InvokeAgentRuntime`.
- **Manual:** `make invoke` sends the payload directly to the runtime.

### 5.2 Entry (`app.py → handler`)
1. Parse the payload into a `Job`.
2. Read `mode` (default `agent`):
   - **`agent`** → run the **Strands agent**, whose only tool is `process_registrations`.
     The agent decides to call the tool, then writes a short report.
   - **`deterministic`** → call `run_pipeline()` directly (no LLM in control flow).
3. Both paths converge on `run_pipeline()` → `read_rows()` → `fill_form()`.

### 5.3 Read the sheet (`sheet_reader.read_rows`)
- HTTP GET the sheet's `export?format=csv` (returns **all** rows).
- Map columns → canonical keys (First Name, Email, Preferred Food, …).
- Fail loudly if the sheet isn't link‑viewable (returns HTML, not CSV).

### 5.4 Fill each row (`form_filler.fill_form`) — the heart of Lab 4
Open **one** AgentCore Browser session (Nova Act owns it; `nova.page` is the Playwright
page). Then, per row:

1. **Dedup gate** — `reserve(form, email)` (DynamoDB conditional put).
   Already submitted? → record `duplicate`, **skip**. New? → continue.
2. **Deterministic fill** — `_fill_known()` types the known fields via fixed
   title→ARIA selectors (`get_by_text(title)` → `get_by_role("textbox"/"radio"/"checkbox")`).
3. **LLM menu pick** — `pick_menu()`:
   - `nova.act("…select the dish most appropriate for a <diet> diet…")`
   - read back which radio is now selected
   - **guardrail** checks the pick vs. the diet's forbidden tags.
4. **Submit + confirm** — click Submit, verify the "response recorded" page.
5. **On failure** — `release()` the dedup marker so the row retries next run; record the
   reason (a diagnostic lists the exact required-unfilled questions).

### 5.5 Report
`run_pipeline` returns `{ submitted, duplicates, menu_picks, failed }`. In **agent** mode
the Strands agent turns that into a one‑paragraph written summary.

---

## 6. A real traced example (from CloudWatch)

For a **Gluten‑Free** attendee, Nova Act reasoned live:

> *"Veg Pasta: contains gluten. Chicken Pizza: crust contains gluten. Tofu Scramble
> Burrito: burritos contain wheat tortillas. Mediterranean Quinoa Salad: quinoa is
> naturally gluten‑free."* → clicked **Mediterranean Quinoa Salad** → submitted.

And a case that shows why the guardrail exists: for a **Vegan** attendee Nova Act picked
**Veg Pasta** (usually egg/dairy → not truly vegan). With `GUARDRAIL=off` it submitted; with
`GUARDRAIL=strict` that row would be **blocked and flagged** for manual follow‑up.

---

## 7. Execution modes

| Mode (`payload.mode`) | Control flow | Needs a Bedrock chat model? | Use for |
|-----------------------|--------------|------------------------------|---------|
| `agent` (default) | Strands agent orchestrates + reports | **Yes** (`MODEL_ID`, e.g. Nova Pro) | when you want reasoned reporting/triage |
| `deterministic` | pipeline runs directly | No | cheapest, fully reproducible daily job |

The per‑field work (Playwright + Nova Act menu) is identical in both modes.

---

## 8. Guardrail modes (`GUARDRAIL` env)

| Value | Behavior |
|-------|----------|
| `off` (default) | trust Nova Act's pick; submit it |
| `warn` | submit, but annotate the row if the pick looks unsafe |
| `strict` | **block** the row if the pick violates the diet (retries next run) |

The guardrail tags each dish (`meat/dairy/egg/gluten/…`) and rejects picks that violate the
preference's forbidden set — it does **not** hardcode the "right" answer.

---

## 9. Nova Act authentication (local key vs runtime IAM)

`form_filler` auto‑selects:

| Where | Auth | Setup |
|-------|------|-------|
| **Local dev** | **API key** | `export NOVA_ACT_API_KEY=<key>` |
| **Deployed runtime** | **AWS IAM** via Nova Act `@workflow` | one‑time `make nova-workflow` (creates the `lab4-form-fill` workflow definition); runtime role has `nova-act:*` |

The deployed container has no key → uses IAM. `make doctor` shows which mode you're in.

---

## 10. Deployment workflow (run in order)

```bash
cd lab4
make whoami          # confirm detected AWS account + region
make install         # .venv (python3.12) + deps + chromium
make doctor          # deps, AWS creds, Nova Act auth mode

make dedup-table     # DynamoDB table            lab4-form-fill-dedup
make nova-workflow   # Nova Act workflow def      lab4-form-fill   (IAM path)

make browser-test    # optional: 1-row AgentCore Browser smoke test
make run-local       # optional: run the whole pipeline locally

make deploy          # register runtime           lab4_form_fill   (entrypoint app.py)
make runtime-policy  # grant runtime role: browser + dynamodb + bedrock + nova-act
make invoke          # fire once (uses events/payload.example.json)

make deploy-lambda   # forwarder Lambda           lab4-form-fill-forwarder
make schedule TIMEZONE=Asia/Kolkata   # daily 05:00 -> Lambda -> runtime
```

**Resources created (in your account, account auto-detected):** DynamoDB table, Nova Act
workflow definition, AgentCore runtime `lab4_form_fill`, runtime execution-role inline
policy `lab4-runtime`, Lambda `lab4-form-fill-forwarder` + role, EventBridge schedule
`lab4-form-fill-daily` + role.

### Choosing the model (`agent` mode)
`app.py` sets `MODEL_ID`. Use a model your account can reach:
- **`us.amazon.nova-pro-v1:0`** — Amazon first‑party, no marketplace agreement (works out of
  the box).
- **`us.anthropic.claude-opus-4-5-20251101-v1:0`** — requires Bedrock **model access** +
  a valid **payment instrument** on the account first.

### Running for all records
Remove `"limit"` from `events/payload.example.json` (dedup still skips already‑submitted
rows). Locally: `make run-local` (no `LIMIT`).

---

## 11. Troubleshooting (issues actually hit, with fixes)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `INVALID_PAYMENT_INSTRUMENT` on `ConverseStream` | account can't complete the Bedrock marketplace agreement for an Anthropic model | fix billing + enable model access, or use a Nova model (`MODEL_ID=us.amazon.nova-pro-v1:0`) |
| `Workflow definition not found` | Nova Act IAM path needs a workflow def | `make nova-workflow` |
| `AccessDenied … StartBrowserSession` | runtime role missing browser perms | `make runtime-policy` |
| `required-unfilled: ['Food Option']` | the menu question title/selector didn't match | fixed — matcher is title‑tolerant (`food|menu option`) |
| `guardrail blocked: …` | LLM picked a dish unsafe for the diet (strict mode) | expected; set `GUARDRAIL=off` or fix the sheet value |
| fewer rows than expected | sheet read used a truncating endpoint | uses `export?format=csv` (all rows), not gviz |

---

## 12. Talking points for the workshop

- **Why not just deterministic?** The Food Option can't be looked up — it's a judgment about
  dishes that changes when the caterer changes the menu. That's the LLM's job.
- **Why the guardrail?** The trace shows the LLM being confidently wrong (burrito "is
  gluten‑free"; pasta "is vegan"). Deterministic code catches what the model gets wrong.
- **Why Strands + AgentCore?** One entrypoint, native to AgentCore Runtime, wraps the
  pipeline as tools and gives you a reasoned report — deployable and scheduled like any other
  runtime, with session replay + CloudWatch for audit.
- **Idempotent + scheduled:** safe to run daily and to re‑deliver; only new registrations
  are submitted.
