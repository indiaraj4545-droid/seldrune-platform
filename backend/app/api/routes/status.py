import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from backend.app.api.dependencies import SessionDep
from backend.app.core.config import settings

router = APIRouter(tags=["status"])


@router.get("/status")
def service_status(session: SessionDep) -> dict[str, Any]:
    database_healthy = True
    database_error: str | None = None
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        database_healthy = False
        database_error = type(exc).__name__

    provider_configured = (
        settings.model_provider == "mock"
        or bool(os.getenv("OPENAI_API_KEY", "").strip())
    )
    ready = database_healthy and provider_configured
    checks: dict[str, Any] = {
        "database": {
            "status": "ok" if database_healthy else "error",
            **({"error": database_error} if database_error else {}),
        },
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
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
    }
