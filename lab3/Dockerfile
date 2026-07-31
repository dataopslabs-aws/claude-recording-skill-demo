# AgentCore Runtime container for Lab 1.
# Playwright base image ships Chromium + system deps, so the browser client and any
# local Playwright both work. The AgentCore starter toolkit (`agentcore launch`) builds
# and pushes this to ECR and registers the runtime for you.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The BedrockAgentCoreApp harness in runtime_handler.py serves the runtime contract.
# EventBridge -> InvokeAgentRuntime delivers the {sheet, form} payload to the entrypoint.
CMD ["python", "runtime_handler.py"]
