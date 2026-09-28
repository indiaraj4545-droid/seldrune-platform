"""Regression tests for the LiveShell privacy/isolation boundary.

The live face/voice media path must remain independent from Seldrune GPT,
prompt orchestration, and persistent cognitive/knowledge-memory services.
Only short-lived transport/session metadata is allowed in this boundary.
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from services.live_media.session_store import LiveSession

REPO_ROOT = Path(__file__).resolve().parents[1]

LIVE_BOUNDARY_PATHS = (
    REPO_ROOT / "services" / "live_media",
    REPO_ROOT / "backend" / "app" / "api" / "routes" / "liveshell_jobs.py",
    REPO_ROOT / "backend" / "app" / "api" / "routes" / "liveshell_mobile.py",
    REPO_ROOT / "backend" / "app" / "web" / "liveshell-face-swap-mobile.js",
)

FORBIDDEN_COUPLINGS = (
    "backend.app.services.model_gateway",
    "backend.app.services.knowledge",
    "backend.app.services.outcome_memory",
    "backend.app.services.executive_outcome_memory",
    "backend.app.api.routes.seldrune_gpt",
    "backend.app.models.memory",
)


def _text_files(path: Path):
    if path.is_file():
        yield path
        return
    for pattern in ("*.py", "*.js"):
        yield from path.rglob(pattern)


def test_live_media_has_no_gpt_or_persistent_memory_coupling():
    offenders: list[str] = []
    for root in LIVE_BOUNDARY_PATHS:
        for path in _text_files(root):
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_COUPLINGS:
                if token in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} -> {token}")
    assert offenders == []


def test_live_session_store_keeps_only_transport_metadata():
    names = {field.name for field in fields(LiveSession)}
    assert names == {"session_id", "user_id", "worker_id", "created_at"}
    assert names.isdisjoint(
        {
            "prompt",
            "prompt_history",
            "transcript",
            "chat_history",
            "source_face",
            "reference_face",
            "audio",
            "video",
            "embedding",
        }
    )
