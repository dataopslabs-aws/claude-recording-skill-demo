#!/usr/bin/env bash
# Package + deploy the forwarder Lambda and its execution role.
#
#   bash deploy/deploy_lambda.sh            # account auto-detected; REGION defaults us-east-1
#   REGION=eu-west-1 RUNTIME=lab3_form_fill bash deploy/deploy_lambda.sh
#
# Prereqs: the runtime is deployed (make deploy). Prints the Lambda ARN on success.
set -euo pipefail

REGION="${REGION:-us-east-1}"
ACCOUNT="${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}"
RUNTIME="${RUNTIME:-lab3_form_fill}"
LAMBDA="${LAMBDA:-lab3-form-fill-forwarder}"
ROLE_NAME="${ROLE_NAME:-lab3-lambda-forwarder}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Render a sub-doc of an IAM json, substituting __ACCOUNT_ID__/__REGION__.
render() {  # $1=file  $2=json-key
  python3 - "$1" "$2" "$ACCOUNT" "$REGION" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))[sys.argv[2]]
print(json.dumps(doc).replace("__ACCOUNT_ID__", sys.argv[3]).replace("__REGION__", sys.argv[4]))
PY
}

# Resolve the runtime ARN (default env for the Lambda + policy resource).
RUNTIME_ARN="$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME}'].agentRuntimeArn | [0]" --output text)"
if [[ -z "$RUNTIME_ARN" || "$RUNTIME_ARN" == "None" ]]; then
  echo "Runtime '${RUNTIME}' not found in ${REGION}. Run 'make deploy' first." >&2
  exit 1
fi
echo "Account: $ACCOUNT   Region: $REGION"
echo "Runtime ARN: $RUNTIME_ARN"

# Create the execution role if missing.
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Creating role $ROLE_NAME ..."
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$(render "$HERE/iam_lambda_role.json" trust_policy)" >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name invoke-runtime \
    --policy-document "$(render "$HERE/iam_lambda_role.json" invoke_policy)"
  echo "Waiting for IAM propagation ..."; sleep 10
fi
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

# Package the function.
TMP="$(mktemp -d)"
cp "$HERE/lambda_forwarder.py" "$TMP/"
( cd "$TMP" && zip -q function.zip lambda_forwarder.py )

# Create or update.
if aws lambda get-function --function-name "$LAMBDA" --region "$REGION" >/dev/null 2>&1; then
  echo "Updating function code ..."
  aws lambda update-function-code --function-name "$LAMBDA" --region "$REGION" \
    --zip-file "fileb://$TMP/function.zip" >/dev/null
  aws lambda update-function-configuration --function-name "$LAMBDA" --region "$REGION" \
    --environment "Variables={AGENT_RUNTIME_ARN=$RUNTIME_ARN}" >/dev/null
else
  echo "Creating function $LAMBDA ..."
  aws lambda create-function --function-name "$LAMBDA" --region "$REGION" \
    --runtime python3.12 --handler lambda_forwarder.handler --role "$ROLE_ARN" \
    --timeout 900 --memory-size 256 --zip-file "fileb://$TMP/function.zip" \
    --environment "Variables={AGENT_RUNTIME_ARN=$RUNTIME_ARN}" >/dev/null
fi
rm -rf "$TMP"

LAMBDA_ARN="$(aws lambda get-function --function-name "$LAMBDA" --region "$REGION" \
  --query 'Configuration.FunctionArn' --output text)"
echo "Lambda ARN: $LAMBDA_ARN"
# Note: InvokeAgentRuntime is synchronous. Lambda timeout is 900s (15 min); a 25-row
# browser fill runs in a few minutes. For much larger batches, move to async or chunk.
