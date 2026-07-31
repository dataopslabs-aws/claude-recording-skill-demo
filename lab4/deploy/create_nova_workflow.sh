#!/usr/bin/env bash
# Create the Nova Act workflow definition used by the AWS-IAM auth path (local runs with
# your IAM creds, and the deployed runtime with its role). Idempotent-ish: a 409/exists is
# fine. Run once per account+region.
#
#   REGION=us-east-1 NOVA_WORKFLOW=lab4-form-fill bash deploy/create_nova_workflow.sh
set -euo pipefail

REGION="${REGION:-us-east-1}"
NOVA_WORKFLOW="${NOVA_WORKFLOW:-lab4-form-fill}"

echo "Creating Nova Act workflow definition '$NOVA_WORKFLOW' in $REGION ..."
aws nova-act create-workflow-definition --name "$NOVA_WORKFLOW" --region "$REGION" \
  && echo "Workflow definition '$NOVA_WORKFLOW' is ACTIVE." \
  || echo "create returned non-zero — it may already exist (that's fine)."

# Note: just --name is required. Nova Act run data is exported to a managed store; if your
# account requires a custom S3 bucket + role, add --output-config accordingly.
