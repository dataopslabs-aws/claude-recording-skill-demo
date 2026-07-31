#!/usr/bin/env bash
# Attach the AgentCore Browser + DynamoDB (+ssm/kms/logs) permissions to the runtime's
# auto-created execution role. `agentcore launch` creates a role that CANNOT start a
# browser session, so the first invoke fails AccessDeniedException until you run this.
#
#   bash deploy/attach_runtime_policy.sh                 # account auto-detected
#   RUNTIME=lab4_form_fill REGION=us-east-1 bash deploy/attach_runtime_policy.sh
set -euo pipefail

REGION="${REGION:-us-east-1}"
ACCOUNT="${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}"
RUNTIME="${RUNTIME:-lab4_form_fill}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Find the runtime's auto-created execution role WITHOUT needing GetAgentRuntime
# (some IAM users can list runtimes but not Get them). Prefer the toolkit config that
# `make deploy` wrote locally; fall back to the newest SDK runtime role for this region.
CONFIG="$HERE/../.bedrock_agentcore.yaml"
ROLE_ARN=""
if [[ -f "$CONFIG" ]]; then
  ROLE_ARN="$(grep -oE 'arn:aws:iam::[0-9]+:role/AmazonBedrockAgentCoreSDKRuntime-[A-Za-z0-9-]+' "$CONFIG" | head -1 || true)"
fi
if [[ -n "$ROLE_ARN" ]]; then
  ROLE_NAME="${ROLE_ARN##*/}"
else
  ROLE_NAME="$(aws iam list-roles \
    --query "sort_by(Roles[?starts_with(RoleName, 'AmazonBedrockAgentCoreSDKRuntime-${REGION}')], &CreateDate)[-1].RoleName" \
    --output text 2>/dev/null || true)"
fi
if [[ -z "$ROLE_NAME" || "$ROLE_NAME" == "None" ]]; then
  echo "Could not find the runtime execution role. Run 'make deploy' first, or set ROLE_NAME=..." >&2
  exit 1
fi
echo "Account: $ACCOUNT   Region: $REGION"
echo "Runtime role: $ROLE_NAME"

# Render the policy (substitute account/region) and attach it inline.
POLICY="$(python3 - "$HERE/iam_runtime_policy.json" "$ACCOUNT" "$REGION" <<'PY'
import json, sys
s = json.dumps(json.load(open(sys.argv[1])))
print(s.replace("__ACCOUNT_ID__", sys.argv[2]).replace("__REGION__", sys.argv[3]))
PY
)"
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name lab4-runtime \
  --policy-document "$POLICY"
echo "Attached lab4-runtime policy to $ROLE_NAME. Wait a few seconds, then 'make invoke'."
