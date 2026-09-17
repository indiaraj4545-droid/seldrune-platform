# Project attribution and usage accounting

Seldrune v1.0 makes project ownership of execution explicit instead of relying only on orchestration metadata.

## Authoritative attribution

Tasks may carry a nullable `project_id`. New project-delivery and project-recovery orchestration tasks receive the project id explicitly. Manual task creation may also provide a project id, but the API accepts it only when the project belongs to the same organization.

Legacy tasks remain valid with `project_id = NULL`. Seldrune does not rewrite historical tasks by guessing from arbitrary task payloads. Legacy project-delivery runs can still resolve their project through the existing governed delivery context, while any non-null task attribution that conflicts with that delivery project is rejected.

Department attribution is derived through the authoritative project relationship: task -> project -> department. This avoids duplicating a mutable department id on each task.

## Billing roll-up

The billing explorer can filter invocations by project or department and exposes project and department usage breakdowns alongside the existing provider/model breakdown. Unattributed legacy tasks remain represented with null project/department attribution rather than being assigned speculatively.

Model invocations continue to distinguish priced usage from unpriced usage. A null `estimated_cost_usd` means unknown/unpriced, never zero.

## Project reconciliation

When a delivery command is synchronized, Seldrune records:

- the subtotal of known model cost,
- the count of unpriced model invocations,
- whether the delivery cost is complete,
- successful resource units.

Known cost is added to `budget_spent_usd`. Unpriced invocations increment the project's `unpriced_model_invocation_count`. If every invocation is priced, an active budget reservation is reconciled with an actual cost and variance. If any invocation is unpriced, the reservation is marked `reconciled_unpriced`, records only the known subtotal and unresolved count, and does not invent an actual total or variance.

A project with unresolved unpriced model usage fails the governed execution budget check until accounting is corrected. This prevents additional automated spend from relying on a budget balance that is known to be incomplete.

## Accounting correction authority

Only `billing:manage` may use the project accounting-correction endpoint. The correction can update the recorded spend and/or unresolved unpriced count and requires a reason. The audit trail records before/after values and the reason.

This is the governed path for reconciling a provider invoice or other authoritative cost source after Seldrune originally observed unpriced model usage.
