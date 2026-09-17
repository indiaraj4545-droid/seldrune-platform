# Seldrune Platform

Core platform for the **Seldrune AI-native virtual organization**.

Seldrune is a reusable operating layer for governed AI work across research, software engineering, automation, ventures, talent, managed operations, and future products.

## Current milestone — Seldrune v1.0

The platform has progressed beyond the original foundation milestone and now includes production-oriented organization, agent, security, governance, audit, billing, and orchestration capabilities.

Current platform capabilities include:

- organization identity, membership administration, RBAC, invitations, and tenant isolation
- rotating refresh sessions, server-side logout/session revocation, login throttling, TOTP MFA, and one-time MFA recovery codes
- security-event monitoring with owner attention integration
- agent registry, model policy, tool grants, immutable configuration revisions, and governed restore
- orchestration, human approval checkpoints, recovery runs, and project delivery workflows
- tool gateway, knowledge/memory, research connectors, signed inbound webhooks, and secret references
- audit explorer, AI usage/cost reporting, budget authority, project/department attribution, and accounting integrity
- owner attention, browser/web-push notification infrastructure, and executive operating surfaces
- PostgreSQL/Alembic migrations, automated tests, GitHub Actions CI, and Render deployment configuration

### v1.0.1 production-recovery patch

The v1.0.1 patch hardens the deployment path by validating Alembic migrations against real PostgreSQL in CI and exercising a production-config startup health check. It also widens Alembic's internal revision identifier column before the first Seldrune migration whose revision ID exceeds Alembic's historical 32-character default.

## Local development

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn backend.app.main:app --reload
```

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Owner console: `http://127.0.0.1:8000/console`
- Status/readiness: `http://127.0.0.1:8000/api/v1/status`

Run quality checks:

```bash
ruff check .
pytest -q
```

## Production deployment

The Render web service runs database migrations before starting the API:

```bash
alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}
```

`/api/v1/status` reports application version, environment, database readiness, and model-provider readiness. Production deploys should not be considered healthy until that endpoint reports `"ready": true` on the intended release version.

## Security

Never commit passwords, API keys, access tokens, private certificates, MFA recovery codes, or production secrets. Use `.env` for local development and managed secret storage or secret references for production systems.

See [`docs/architecture.md`](docs/architecture.md) for the broader platform direction and [`docs/identity-access.md`](docs/identity-access.md) for identity/security controls.
