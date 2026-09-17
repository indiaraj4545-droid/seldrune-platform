# Identity and access

Seldrune Core v0.3 introduced the first authentication and authorization boundary. Later releases have hardened that boundary for multi-user production use.

## Authentication

- Passwords are hashed with the recommended `pwdlib` password hash configuration.
- Access tokens are signed JWTs with an expiry and a required token type.
- New access tokens carry a unique `jti` so simultaneous sessions are independently revocable.
- `POST /api/v1/auth/logout` stores only a SHA-256 token fingerprint and revokes that bearer session immediately.
- Legacy valid access tokens without `jti` remain compatible until expiry or explicit revocation.
- Production refuses to start with the development JWT secret.
- Authentication failures return the same response for unknown users and bad passwords.
- Repeated bad-password attempts are rate-limited per credential/source pair using only a keyed SHA-256 throttle digest; raw credential identifiers and source addresses are not stored in throttle records.

## Registration and invitations

`POST /api/v1/auth/register` is the one-time owner bootstrap flow. After bootstrap, organization membership is expanded through expiring one-time invitations. Invitation tokens are stored only as hashes, support revocation and replay protection, and enforce role ceilings so administrators cannot mint owner authority.

## Authorization

Organization authorization remains database-backed. The JWT identifies the user; the server then loads the current membership and evaluates the role against the RBAC permission map. Roles are not trusted merely because they appear in a token.

Current roles:

- owner
- admin
- member
- auditor

## Implemented production controls

- invite-only post-bootstrap onboarding,
- organization member administration and role ceilings,
- server-side access-token revocation,
- per-session logout,
- login brute-force rate limiting,
- database-backed RBAC,
- audit trails for security-relevant authenticated actions,
- secret-reference management without secret-value persistence.

## Production controls still required

Before accepting broad external customer access, complete:

- email verification,
- MFA/passkeys,
- refresh-token rotation or an external identity provider,
- account recovery,
- cloud secret-manager integration for secret values,
- expanded security-event monitoring and alerting.
