from fastapi import APIRouter

from backend.app.core.config import settings

router = APIRouter(tags=["status"])


@router.get("/status")
def service_status() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "seldrune-platform",
        "version": settings.app_version,
    }
