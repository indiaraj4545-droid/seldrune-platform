# Identity and access

Seldrune Core v0.3 introduced the first authentication and authorization boundary. Later releases have hardened that boundary for multi-user production use.

## Authentication

- Passwords are hashed with the recommended `pwdlib` password hash configuration.
- Access tokens are signed JWTs with an expiry and a required token type.
- New access tokens carry a unique `jti` so simultaneous sessions are independently revocable.
- New access tokens also carry a stable session-family `sid` when issued with a refresh session.
- Opaque refresh tokens rotate exactly once and are stored only as SHA-256 digests.
- Refresh-token reuse revokes the entire refresh family before the request is rejected.
- Refresh families expire after a bounded lifetime and are revoked by normal session logout.
- `POST /api/v1/auth/logout` stores only a SHA-256 access-token fingerprint and revokes that bearer session immediately.
- Legacy valid access tokens without `sid` remain compatible until expiry or explicit access-token revocation.
- Production refuses to start with the development JWT secret.
- Authentication failures return the same response for unknown users and bad passwords.
- Repeated bad-password or bad-MFA attempts are rate-limited per credential/source pair using only a keyed SHA-256 throttle digest; raw credential identifiers and source addresses are not stored in throttle records.

## Multi-factor authentication

Users can enroll a standard 6-digit TOTP authenticator through authenticated setup, confirmation, and disable endpoints. Setup requires current-password re-authentication, enabling requires a valid authenticator code, and disabling requires both the current password and a valid authenticator code.

Seldrune does not persist the base32 TOTP seed. It stores only a random per-user enrollment nonce and derives the authenticator secret with HMAC domain separation from the server authentication key, user id, and nonce. Restarting setup before enable rotates the nonce; disabling clears it. MFA state changes revoke every active refresh-token family for the user.

When MFA is enabled, password login and existing-user invitation acceptance require the TOTP code before any new access/refresh session is issued. Existing refresh sessions created before an MFA state change are invalidated.

## Registration and invitations

`POST /api/v1/auth/register` is the one-time owner bootstrap flow. After bootstrap, organization membership is expanded through expiring one-time invitations. Invitation tokens are stored only as hashes, support revocation and replay protection, and enforce role ceilings so administrators cannot mint owner authority.

## Authorization

Organization authorization remains database-backed. The JWT identifies the user; the server then loads the current membership and evaluates the role against the RBAC permission map. Roles are not trusted merely because they appear in a token.

Current roles:

- owner
- admin
- member
- auditor

## Security monitoring

High-signal security events are stored in an organization-scoped security center. Owner, admin, and auditor roles can read events; owner and admin roles can acknowledge them. Open critical and warning events feed the existing owner-attention snapshot and privacy-safe counts-only push envelope.

Initial producers include refresh-token reuse detection and inbound webhook authentication rejection. Security-event records intentionally exclude raw passwords, bearer tokens, refresh tokens, webhook signatures, request bodies, and secret values.

## Implemented production controls

- invite-only post-bootstrap onboarding,
- organization member administration and role ceilings,
- TOTP multi-factor authentication,
- rotating refresh sessions with replay-family revocation,
- server-side access-token revocation,
- per-session logout,
- login brute-force rate limiting,
- database-backed RBAC,
- audit trails for security-relevant authenticated actions,
- organization-scoped security-event monitoring and owner alerts,
- secret-reference management without secret-value persistence.

## Production controls still required

Before accepting broad external customer access, complete:

- email verification,
- account recovery,
- cloud secret-manager integration for secret values.
