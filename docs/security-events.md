# Security event center

Seldrune v0.97 introduces durable organization-scoped security-event monitoring for high-signal security conditions.

## Access model

- `security:read`: owner, admin, auditor
- `security:manage`: owner, admin
- members have neither permission

Security events are always filtered by organization membership and organization id.

## Initial event producers

- `refresh_token_reuse` — critical; created for each current organization membership of the affected user after refresh-token replay is detected and the refresh family is revoked.
- `webhook_authentication_rejected` — warning; created for the webhook endpoint organization when signature authentication fails.

## Privacy

Security-event details must not contain passwords, bearer tokens, refresh tokens, token hashes, webhook signatures, request bodies, or secret values. Owner browser notifications remain counts-only and contain no resource ids or event details.

## Lifecycle

Events start as `open`. Owner/admin acknowledgement changes the event to `acknowledged`, records acknowledgement metadata, and removes the event from subsequent owner-attention snapshots. Acknowledgement is idempotent and does not execute remediation automatically.
