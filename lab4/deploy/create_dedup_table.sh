#!/usr/bin/env bash
# Create the DynamoDB idempotency table (partition key 'pk', on-demand billing).
#
#   REGION=us-east-1 DEDUP_TABLE=lab4-form-fill-dedup bash deploy/create_dedup_table.sh
set -euo pipefail

REGION="${REGION:-us-east-1}"
TABLE="${DEDUP_TABLE:-lab4-form-fill-dedup}"

if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "Table $TABLE already exists."
  exit 0
fi

aws dynamodb create-table --table-name "$TABLE" --region "$REGION" \
  --attribute-definitions AttributeName=pk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST >/dev/null
aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
echo "Created table $TABLE."
