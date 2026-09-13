# Autonomous Execution Engine v0.7

Seldrune v0.7 connects orchestration planning to agent execution.

## Execution flow

1. An orchestration run already contains ordered steps and durable tasks.
2. The autonomous executor processes steps in sequence.
3. A step runs only when its task is assigned to an active Agentic AI.
4. Successful task output is compacted and attached to the next task as `upstream_results`.
5. The Agent Runtime sends the task to the configured Model Gateway provider.
6. Task, model invocation, task event, and audit records remain durable.
7. Execution stops safely when a dependency is unmatched, a task is cancelled, or a failure
   reaches the configured retry limit.
8. Calling the execution endpoint again resumes the run and skips already successful steps.

## API

`POST /api/v1/organizations/{organization_id}/orchestrations/{run_id}/execute`

Example body:

```json
{
  "stop_on_failure": true,
  "max_steps": 50,
  "max_retries_per_step": 0,
  "max_upstream_text_chars": 4000
}
```

Automatic retries are bounded to a maximum of two retries per step. A retry creates a new
durable task and preserves the failed task as historical evidence instead of erasing it.

## Safety and reliability

- Execution is sequential in v0.7; parallel execution is intentionally deferred.
- Unmatched steps block downstream execution by default.
- Successful steps are idempotently skipped on resume.
- Raw provider credentials are never stored in orchestration records.
- Upstream model text is truncated before being passed to later agents.
- Every autonomous run start, completion, and retry is audit logged.
- Models can generate results, but v0.7 does not grant arbitrary external tool permissions.

This design gives Seldrune a controlled autonomous loop while keeping human-visible history
and clear failure boundaries.
