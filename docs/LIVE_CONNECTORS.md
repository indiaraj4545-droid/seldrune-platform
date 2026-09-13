# Seldrune v0.11: Governed Live Connectors

Seldrune live research connectors are read-only and policy constrained.

## Runtime references

Credential values are not stored in the Seldrune database. A `SecretReference` stores only a provider and locator. In v0.11 the supported provider is `env`, so operations can provision an environment-variable name and the runtime resolves it only while executing a connector.

The public API intentionally does not expose secret values. Runtime-reference provisioning remains an operational/admin responsibility in this release.

## Public web connector

The `web` provider accepts only explicitly configured HTTPS URLs. Every hostname must also appear in the connector's `allowed_hosts` list. The default transport resolves the host and rejects loopback, private, link-local, reserved, and other non-public addresses. Responses are capped at 1 MB and requests have a fixed timeout.

## GitHub connector

The `github` provider reads repository README content only. Every repository must appear in the connector's `allowed_repositories` list. An optional runtime reference may supply authentication at execution time; the credential itself is never written to connector configuration, source records, Knowledge entries, or audit logs.

## Request and approval controls

Each connector has `max_requests_per_run` to bound external requests during one research execution. Connectors can also set `approval_mode=always`. Those connectors execute only when the calling organization member has `research:approve` permission.

## CI and testing

CI uses a fake HTTP transport and never contacts live external services. Live connectors are therefore testable without network access or credentials.

## Current limits

v0.11 is intentionally conservative. It does not provide arbitrary crawling, arbitrary HTTP methods, shell access, arbitrary GitHub repository access, or a public secrets CRUD API. Distributed/global rate limiting and managed cloud-vault providers are future milestones.
