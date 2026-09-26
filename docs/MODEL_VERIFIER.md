# Independent Model Verifier Fallback

This module implements the `model_verifier_fallback` roadmap stage as a
fail-closed verification policy for model outputs.

It does **not** call models itself. The existing model gateway remains
responsible for provider execution, budgets, credentials, and invocation
recording.

## Contract

A verification plan binds the source model output by SHA-256 and records:

- source provider and model;
- required verifier capabilities;
- total verification budget;
- eligible independent verifier candidates; and
- deterministic cheapest-first ordering.

A candidate is excluded when it is the same provider+model as the source, lacks
required capabilities, falls below the confidence floor, exceeds the budget, or
is not allowed by policy.

## Escalation

Verification always begins with the cheapest eligible independent candidate.

- `pass`: verification succeeds immediately and no expensive fallback is used.
- `fail`: a more expensive verifier may be tried only if one remains inside the
  total budget.
- `inconclusive`: follows the same bounded escalation rule.
- no remaining verifier: terminal `rejected` after a final failure, or
  `unverified_exhausted` after inconclusive evidence.

Every attempt must match the original output digest and include provenance
references. Skipping a cheaper planned verifier, changing the digest, omitting
evidence, or exceeding the total budget fails closed.

This policy reduces unnecessary model spend while preserving independent
verification and does not treat free-form model output as completion evidence.
