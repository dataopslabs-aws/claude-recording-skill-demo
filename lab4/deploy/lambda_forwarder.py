"""
Thin EventBridge -> AgentCore Runtime forwarder.

Use this when the EventBridge Scheduler universal `invokeAgentRuntime` target isn't
available in your account: the daily schedule invokes THIS Lambda with the {sheet, form}
payload as its event, and the Lambda calls InvokeAgentRuntime, forwarding the payload
unchanged.

Event shapes accepted:
  - bare payload:      {"sheet": {...}, "form": {...}, "region": "us-east-1"}
  - wrapped:           {"agentRuntimeArn": "...", "payload": {"sheet": {...}, "form": {...}}}

The runtime ARN comes from the event (`agentRuntimeArn`) or the AGENT_RUNTIME_ARN env var.
No secrets in the event — credentials come from the Lambda execution role.

NOTE: confirm the boto3 client name ("bedrock-agentcore") and invoke_agent_runtime
parameter names against your installed SDK version; they can vary.
"""

import json
import os

import boto3

_agentcore = boto3.client("bedrock-agentcore")


def handler(event, context=None):
    arn = event.get("agentRuntimeArn") or os.environ.get("AGENT_RUNTIME_ARN")
    if not arn:
        raise ValueError("agentRuntimeArn missing in event and AGENT_RUNTIME_ARN unset")

    payload = event.get("payload") if "payload" in event else event
    if "sheet" not in payload or "form" not in payload:
        raise ValueError("payload must contain 'sheet' and 'form'")

    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=arn,
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode("utf-8"),
    )

    body = resp.get("response")
    out = body.read().decode("utf-8", "ignore") if hasattr(body, "read") else body
    print(f"invoke_agent_runtime ok arn={arn} -> {str(out)[:800]}")
    return {"statusCode": 200, "runtimeArn": arn}
