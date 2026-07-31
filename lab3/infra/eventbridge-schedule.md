# Daily schedule + payload delivery (Lab 3)

The schedule and the parameters are the same object: an **EventBridge Scheduler** schedule
whose **Input** is the `{sheet, form}` payload. Fire it once a day at 05:00; change the
Input to retarget the sheet/form — no redeploy. `make schedule` does all of this for you;
this doc explains what it builds.

> **Naming note:** "CloudWatch for scheduling" really means **EventBridge Scheduler**
> (the successor to CloudWatch Events / scheduled rules). CloudWatch itself is where the
> **logs and metrics** land (the AgentCore Runtime and Browser sessions emit logs/traces
> to CloudWatch + AgentCore observability). So: EventBridge = *when* + *what payload*,
> CloudWatch = *what happened*.

## 1. The schedule (daily 05:00 → forwarder Lambda)

Cron for 05:00 every day is `cron(0 5 * * ? *)`. **Set the timezone explicitly** — the
default is UTC, which is almost never what "everyday 5:00" means. `make schedule` targets
the `lab3-form-fill-forwarder` Lambda, which calls `InvokeAgentRuntime`:

```bash
make schedule TIMEZONE=Asia/Kolkata
```

Under the hood (`deploy/create_schedule.sh`, account auto-detected):

```bash
aws scheduler create-schedule \
  --name lab3-form-fill-daily \
  --schedule-expression 'cron(0 5 * * ? *)' \
  --schedule-expression-timezone 'Asia/Kolkata' \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target '{ "Arn": "<forwarder-lambda-arn>",
              "RoleArn": "arn:aws:iam::<auto>:role/lab3-scheduler-invoke",
              "Input": "<contents of events/payload.example.json>" }'
```

The Input is exactly `events/payload.example.json`. The forwarder Lambda receives it as its
event and forwards it to `InvokeAgentRuntime`; the runtime parses it via `Job.from_payload`.

## 2. Changing the payload (retarget a run)

Composability lives here: point the daily job at a different sheet or form by editing
`events/payload.example.json` and re-running `make schedule` (add `"limit": N` for a capped
run). For several forms on different cadences, create one schedule per payload
(`SCHEDULE_NAME=...`); a **schedule group** keeps them tidy.

## 3. IAM (auto-created, least privilege)

- **Scheduler role** (`lab3-scheduler-invoke`): `lambda:InvokeFunction` on the forwarder
  only. Created by `make schedule` from `deploy/iam_scheduler_role.json`.
- **Lambda role** (`lab3-lambda-forwarder`): `bedrock-agentcore:InvokeAgentRuntime` on the
  runtime + basic logging. Created by `make deploy-lambda`.
- **Runtime execution role** (auto-created by `agentcore launch`): needs
  `bedrock-agentcore:*Browser*` + `dynamodb:PutItem/DeleteItem/GetItem` (+ ssm/kms/logs) —
  attached by `make runtime-policy`. No Google creds ever travel in the payload.

## 4. Logs (CloudWatch)

AgentCore Runtime and Browser stream logs/traces to CloudWatch and AgentCore
observability. Tail a run:

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT --since 1h --follow
```

Add a CloudWatch **alarm** on the schedule's failed-invocation metric and on a custom
"submitted < expected" metric the handler can emit, so a bad daily run pages you instead of
failing silently.
