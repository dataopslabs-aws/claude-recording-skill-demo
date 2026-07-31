#!/usr/bin/env bash
# Create the daily 05:00 EventBridge schedule that invokes the forwarder Lambda with the
# {sheet, form} payload from events/payload.example.json. The Lambda calls InvokeAgentRuntime.
#
#   bash deploy/create_schedule.sh                       # account auto-detected
#   TIMEZONE=Asia/Kolkata bash deploy/create_schedule.sh
#
# Prereqs: the forwarder Lambda exists (make deploy-lambda) and this script will create the
# scheduler role from deploy/iam_scheduler_role.json if it doesn't exist yet.
set -euo pipefail

REGION="${REGION:-us-east-1}"
ACCOUNT="${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}"
LAMBDA="${LAMBDA:-lab3-form-fill-forwarder}"
SCHEDULE_NAME="${SCHEDULE_NAME:-lab3-form-fill-daily}"
TIMEZONE="${TIMEZONE:-America/Los_Angeles}"     # <-- set YOUR timezone; default is NOT UTC on purpose
SCHEDULER_ROLE_ARN="${SCHEDULER_ROLE_ARN:-arn:aws:iam::${ACCOUNT}:role/lab3-scheduler-invoke}"
HERE="$(cd "$(dirname "$0")" && pwd)"

render() {  # $1=file  $2=json-key -> substitute account/region
  python3 - "$1" "$2" "$ACCOUNT" "$REGION" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))[sys.argv[2]]
print(json.dumps(doc).replace("__ACCOUNT_ID__", sys.argv[3]).replace("__REGION__", sys.argv[4]))
PY
}

LAMBDA_ARN="$(aws lambda get-function --function-name "$LAMBDA" --region "$REGION" \
  --query 'Configuration.FunctionArn' --output text 2>/dev/null || true)"
if [[ -z "$LAMBDA_ARN" || "$LAMBDA_ARN" == "None" ]]; then
  echo "Lambda '${LAMBDA}' not found in ${REGION}. Run 'make deploy-lambda' first." >&2
  exit 1
fi
echo "Account: $ACCOUNT   Region: $REGION"
echo "Target Lambda ARN: $LAMBDA_ARN"

# Ensure the scheduler role exists and trusts EventBridge Scheduler.
ROLE_NAME="${SCHEDULER_ROLE_ARN##*/}"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Creating scheduler role $ROLE_NAME ..."
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$(render "$HERE/iam_scheduler_role.json" trust_policy)" >/dev/null
  aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name invoke \
    --policy-document "$(render "$HERE/iam_scheduler_role.json" invoke_policy)"
  echo "Waiting for IAM propagation ..."; sleep 10
fi

# The schedule Input == the payload the runtime receives. Edit events/payload.example.json
# to point at your own sheet/form (add "limit": N for a capped run). Region is injected.
INPUT="$(python3 - "$HERE/../events/payload.example.json" "$REGION" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
p.setdefault("region", sys.argv[2])
print(json.dumps(p))
PY
)"

# create or replace
aws scheduler delete-schedule --name "$SCHEDULE_NAME" --region "$REGION" >/dev/null 2>&1 || true
aws scheduler create-schedule \
  --name "$SCHEDULE_NAME" \
  --region "$REGION" \
  --schedule-expression 'cron(0 5 * * ? *)' \
  --schedule-expression-timezone "$TIMEZONE" \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "{
    \"Arn\": \"${LAMBDA_ARN}\",
    \"RoleArn\": \"${SCHEDULER_ROLE_ARN}\",
    \"Input\": $(python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' <<<"$INPUT")
  }"
echo "Created schedule '${SCHEDULE_NAME}' (daily 05:00 ${TIMEZONE}) -> ${LAMBDA}."
