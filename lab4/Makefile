REGION  ?= us-east-1
# AWS account is auto-detected from your credentials — no need to edit. Override if needed.
ACCOUNT ?= $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null)
RUNTIME ?= lab4_form_fill
LAMBDA  ?= lab4-form-fill-forwarder
DEDUP_TABLE ?= lab4-form-fill-dedup
NOVA_WORKFLOW ?= lab4-form-fill
PAYLOAD ?= events/payload.example.json
# Single unified entrypoint. Choose mode per invocation via the payload: {"mode":"agent"}
# (default, Strands agent) or {"mode":"deterministic"} (no LLM in control flow).
ENTRYPOINT ?= app.py

# Bootstrap interpreter used ONLY to create the venv. Override if 3.12 is elsewhere:
#   make install PYTHON=/opt/homebrew/bin/python3.12
PYTHON  ?= python3.12

VENV      := .venv
VENV_PY   := $(VENV)/bin/python
AGENTCORE := $(VENV)/bin/agentcore

.PHONY: help venv install browser-test run-local deploy runtime-policy invoke dedup-table nova-workflow deploy-lambda schedule doctor whoami clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

whoami:         ## show the detected AWS account + region
	@echo "ACCOUNT=$(ACCOUNT)  REGION=$(REGION)"

venv:           ## create .venv with $(PYTHON)
	@test -x $(VENV_PY) || { echo "Creating venv with $(PYTHON) ($$($(PYTHON) --version))"; $(PYTHON) -m venv $(VENV); }
	@$(VENV_PY) -m pip install --quiet --upgrade pip

install: venv   ## create venv + install deps + chromium
	$(VENV_PY) -m pip install -r requirements.txt
	$(VENV_PY) -m playwright install chromium

doctor: venv    ## check interpreter, deps, AWS creds, and Nova Act auth
	@$(VENV_PY) --version
	@$(VENV_PY) -c "import bedrock_agentcore, playwright, nova_act, strands; print('deps: ok')" || echo "deps: MISSING — run 'make install'"
	@$(VENV_PY) -c "import boto3; print('aws:', boto3.client('sts').get_caller_identity()['Arn'])" || echo "aws: NO CREDENTIALS — export AWS_PROFILE or keys"
	@[ -n "$$NOVA_ACT_API_KEY" ] && echo "nova: API key set (local mode)" || echo "nova: no API key — runtime uses AWS IAM via @workflow '$(NOVA_WORKFLOW)' (run 'make nova-workflow' once)"

browser-test: venv  ## REAL AgentCore Browser smoke test (one row) — needs AWS access
	$(VENV_PY) test_agentcore_browser.py

run-local: venv     ## full pipeline (read sheet -> fill form); set LIMIT=2 to cap rows
	LIMIT=$(LIMIT) DEDUP_TABLE=$(DEDUP_TABLE) $(VENV_PY) local_run.py $(PAYLOAD)

deploy: venv        ## build + register the AgentCore runtime (unified entrypoint app.py)
	$(AGENTCORE) configure --entrypoint $(ENTRYPOINT) --name $(RUNTIME) --region $(REGION)
	$(AGENTCORE) launch

runtime-policy:     ## attach browser + dynamodb perms to the runtime execution role
	REGION=$(REGION) ACCOUNT=$(ACCOUNT) RUNTIME=$(RUNTIME) DEDUP_TABLE=$(DEDUP_TABLE) bash deploy/attach_runtime_policy.sh

invoke: venv        ## invoke the deployed runtime once with $(PAYLOAD)
	$(AGENTCORE) invoke "$$(cat $(PAYLOAD))"

dedup-table:        ## create the DynamoDB idempotency table
	REGION=$(REGION) DEDUP_TABLE=$(DEDUP_TABLE) bash deploy/create_dedup_table.sh

nova-workflow:      ## create the Nova Act workflow definition (AWS IAM path; runtime only)
	REGION=$(REGION) NOVA_WORKFLOW=$(NOVA_WORKFLOW) VENV_ACT=$(VENV)/bin/act bash deploy/create_nova_workflow.sh

deploy-lambda:      ## package + deploy the forwarder Lambda (+ its role)
	REGION=$(REGION) ACCOUNT=$(ACCOUNT) RUNTIME=$(RUNTIME) LAMBDA=$(LAMBDA) bash deploy/deploy_lambda.sh

schedule:           ## daily 05:00 EventBridge schedule -> forwarder Lambda
	REGION=$(REGION) ACCOUNT=$(ACCOUNT) LAMBDA=$(LAMBDA) bash deploy/create_schedule.sh

clean:              ## remove the venv
	rm -rf $(VENV)
