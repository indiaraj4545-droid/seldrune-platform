# Model Gateway and Agent Runtime

Seldrune v0.6 separates agent execution from model providers.

## Runtime flow

1. A task must be assigned to an active agent.
2. The agent runtime resolves provider and model preferences from `runtime_config`.
3. The task moves from `assigned` to `running` before the provider call begins.
4. The Model Gateway invokes the configured provider.
5. Usage metadata is written to `model_invocations`.
6. The task finishes as `succeeded` or `failed` and an audit event is recorded.

## Providers

`mock` is the development and CI default. It makes no network request.

`openai` uses the official OpenAI Python SDK and the Responses API. Provider credentials are
read by the provider SDK from its normal environment configuration. Credentials must never be
stored in agent `runtime_config`, database rows, source files, task inputs, or GitHub.

## Agent runtime configuration

Typical non-secret configuration:

```json
{
  "provider": "openai",
  "model": "your-approved-model",
  "instructions": "Act as Seldrune's research specialist.",
  "max_output_tokens": 1200,
  "input_cost_per_million": 0,
  "output_cost_per_million": 0
}
```

Pricing values are optional operator-supplied metadata. Seldrune does not hard-code provider
prices because pricing can change. If both rates are provided, the invocation ledger records an
estimated USD cost from actual token usage.

## Data handling

The invocation ledger stores provider, model, token counts, latency, status, response identifier,
and optional estimated cost. It intentionally does not duplicate raw prompts or model output.
Task output remains attached to the task, where future retention and redaction policies can be
applied centrally.

## Current limitation

Execution is synchronous in v0.6. A production worker queue, retry policy, rate limits,
concurrency controls, and automatic orchestration-run execution belong in later milestones.
