import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api.dependencies import SessionDep
from backend.app.core.config import settings

router = APIRouter(tags=["status"])
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_PRODUCTION_ENVIRONMENTS = {"prod", "production"}


@lru_cache
def _expected_schema_revision() -> str | None:
    config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_PROJECT_ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def _release_provenance() -> dict[str, str | None]:
    candidates = (
        ("seldrune", settings.release_sha),
        ("render", os.getenv("RENDER_GIT_COMMIT")),
        ("github", os.getenv("GITHUB_SHA")),
    )
    for source, value in candidates:
        normalized = (value or "").strip()
        if normalized:
            return {"sha": normalized, "source": source}
    return {"sha": None, "source": None}


def _schema_check(session: SessionDep) -> dict[str, Any]:
    expected_revision: str | None = None
    expected_error: str | None = None
    try:
        expected_revision = _expected_schema_revision()
    except Exception as exc:
        expected_error = type(exc).__name__

    current_revision: str | None = None
    current_error: str | None = None
    try:
        current_revision = session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception as exc:
        session.rollback()
        current_error = type(exc).__name__

    schema_current = (
        expected_revision is not None
        and current_revision is not None
        and current_revision == expected_revision
    )
    if schema_current:
        check_status = "ok"
    elif current_error is not None or expected_error is not None:
        check_status = "unavailable"
    else:
        check_status = "mismatch"

    return {
        "status": check_status,
        "schema_current": schema_current,
        "current_revision": current_revision,
        "expected_revision": expected_revision,
        "required": settings.environment.lower() in _PRODUCTION_ENVIRONMENTS,
        **({"current_error": current_error} if current_error else {}),
        **({"expected_error": expected_error} if expected_error else {}),
    }


def _status_payload(session: SessionDep) -> dict[str, Any]:
    database_healthy = True
    database_error: str | None = None
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        session.rollback()
        database_healthy = False
        database_error = type(exc).__name__

    schema = _schema_check(session) if database_healthy else {
        "status": "unavailable",
        "schema_current": False,
        "current_revision": None,
        "expected_revision": _expected_schema_revision(),
        "required": settings.environment.lower() in _PRODUCTION_ENVIRONMENTS,
        "current_error": database_error,
    }
    provider_configured = (
        settings.model_provider == "mock"
        or bool(os.getenv("OPENAI_API_KEY", "").strip())
    )
    schema_ready = not schema["required"] or schema["schema_current"]
    ready = database_healthy and provider_configured and schema_ready
    checks: dict[str, Any] = {
        "database": {
            "status": "ok" if database_healthy else "error",
            **({"error": database_error} if database_error else {}),
        },
        "schema": schema,
        "model_provider": {
            "status": "ok" if provider_configured else "unconfigured",
            "provider": settings.model_provider,
            "model": settings.model_default,
            "live_ai": settings.model_provider == "openai" and provider_configured,
        },
    }
    return {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "service": "seldrune-platform",
        "version": settings.app_version,
        "environment": settings.environment,
        "release": _release_provenance(),
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
    }


@router.get("/status")
def service_status(session: SessionDep) -> dict[str, Any]:
    return _status_payload(session)


@router.get("/ready")
def service_readiness(session: SessionDep) -> JSONResponse:
    payload = _status_payload(session)
    return JSONResponse(
        status_code=200 if payload["ready"] else 503,
        content=payload,
    )
