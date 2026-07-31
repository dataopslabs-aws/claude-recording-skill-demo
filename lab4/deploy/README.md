# Deploy reference (Lab 4)

> For the full step-by-step workshop walkthrough, see **[`../../ImplementationPlan.md`](../../ImplementationPlan.md)**.
> This file is the quick command reference.

Run from an AWS-connected environment (your laptop, or CI) — the AgentCore Browser can't run
inside the Cowork sandbox. **Your AWS account is auto-detected** from your credentials
(`aws sts get-caller-identity`); nothing here has a hardcoded account number. Override the
region with `REGION=...` and resource names with the Makefile variables if you like.

## One-time per participant

```bash
cd lab4
make whoami          # confirm the detected ACCOUNT + REGION
make install         # .venv (python3.12) + deps + chromium
make doctor          # interpreter + deps + AWS creds check
```

## Deploy order

```bash
make dedup-table     # DynamoDB idempotency table (lab4-form-fill-dedup)
make browser-test    # optional: one-row AgentCore Browser smoke test
make run-local LIMIT=2   # optional: read sheet -> fill 2 rows locally
make deploy          # register the AgentCore runtime (lab4_form_fill)
make runtime-policy  # attach browser + dynamodb perms to the runtime's auto-created role
make invoke          # fire the runtime once with events/payload.example.json
make deploy-lambda   # forwarder Lambda (lab4-form-fill-forwarder) + role
make schedule TIMEZONE=Asia/Kolkata   # daily 05:00 in your zone
```

### Why `make runtime-policy` is required

`agentcore launch` auto-creates an execution role (`AmazonBedrockAgentCoreSDKRuntime-*`)
that can run the container but **cannot start a browser session**, so the first `make
invoke` fails `AccessDeniedException: ...StartBrowserSession`. `make runtime-policy` finds
that role and attaches `iam_runtime_policy.json` (granting `bedrock-agentcore:*Browser*`,
`dynamodb:PutItem/DeleteItem/GetItem`, ssm/kms/logs), with your account/region substituted
in. Re-run `make invoke` afterward.

## Full chain

**EventBridge Scheduler (05:00) → `lab4-form-fill-forwarder` Lambda → `InvokeAgentRuntime`
→ runtime reads the sheet + fills the form via the AgentCore Browser Tool → DynamoDB dedup.**

## Files here

| File | Purpose |
|------|---------|
| `lambda_forwarder.py` | forwards the payload to `InvokeAgentRuntime` |
| `deploy_lambda.sh` | package + deploy the Lambda and its role |
| `create_schedule.sh` | daily 05:00 schedule + scheduler role |
| `attach_runtime_policy.sh` | grant the runtime role browser + dynamodb perms |
| `create_dedup_table.sh` | create the DynamoDB idempotency table |
| `iam_runtime_policy.json` · `iam_scheduler_role.json` · `iam_lambda_role.json` | IAM templates (`__ACCOUNT_ID__`/`__REGION__` substituted at apply time) |

## Notes to verify for your account

- **AgentCore Browser IAM**: `bedrock-agentcore:*Browser*` covers `StartBrowserSession` and
  the automation-stream connect. Tighten `Resource` from `*` if your security posture needs it.
- **SDK versions**: `BrowserClient` / `generate_ws_headers` can change between
  `bedrock-agentcore` releases — pin versions in `requirements.txt`.
- **Toolkit deprecation**: `bedrock-agentcore-starter-toolkit` still works; AWS now points to
  the `@aws/agentcore` CLI (`npm i -g @aws/agentcore`).
