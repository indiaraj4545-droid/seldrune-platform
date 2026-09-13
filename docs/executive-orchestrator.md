# Executive Orchestrator v0.5

The Executive Orchestrator converts a business objective into an auditable orchestration run.

Current responsibilities:

- accept an organization objective and optional context
- use an explicit plan when supplied, otherwise create a deterministic baseline plan
- match each step to the best active agent using declared capabilities
- create durable tasks for every step
- leave unmatched work queued rather than inventing an agent
- track orchestration status from the underlying task states
- preserve step ordering, match score, task links, and audit history

The deterministic planner is intentionally replaceable. A future Model Gateway can generate the plan while reusing the same orchestration, task, permission, database, and audit layers.

This version does not claim that an external AI model has executed a task. It coordinates registered agents and creates the durable work graph that later runtimes will execute.
