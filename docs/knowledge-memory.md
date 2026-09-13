# Knowledge and Memory Layer v0.9

Seldrune v0.9 adds durable organizational knowledge and scoped operational memory.

## Knowledge entries

Knowledge entries are organization-owned records intended to remain useful across many tasks. Each entry stores a title, content, kind, tags, provenance fields, source URI, and metadata. Typical entries include research findings, internal procedures, decisions, validated results, and reference documents.

## Memory items

Memory items are shorter operational records with one of three scopes:

- organization: reusable across the organization
- agent: visible to a specific agent plus organization context
- task: tied to one task

Memory items carry an importance score and may optionally expire.

## Retrieval

The v0.9 retriever is deterministic. It tokenizes the task and ranks matching knowledge and memory using title, tags, content, and memory importance. This gives Seldrune a testable baseline without claiming semantic-vector search before an embedding store is configured.

The retrieval interface intentionally returns stable references such as `knowledge:<uuid>` and `memory:<uuid>`. Those references are stored with task outputs and result memories so the platform can later show internal provenance and citations.

## Agent runtime integration

Before an assigned agent executes, Seldrune builds a retrieval query from the task title, objective, and input data. Relevant same-organization context is compacted and injected into the model request. The references used are recorded in task events, audit details, and the task output.

After successful execution, the result is stored as task-scoped memory. Future tasks can therefore reuse validated prior work instead of always starting from zero.

## Isolation and limits

Retrieval is always filtered by organization. Agent-scoped and task-scoped memories are only included for the matching agent or task. Expired memory is ignored. Retrieval count and injected context size are bounded through environment settings.

## Later upgrades

The next retrieval upgrade can add embeddings and pgvector behind the same service interface. Chunking, document ingestion, richer citation spans, confidence scoring, deduplication, and retention policies can also be added without changing the Agent Runtime contract introduced here.
