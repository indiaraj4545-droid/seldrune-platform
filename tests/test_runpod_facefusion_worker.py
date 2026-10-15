import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.live_media import runpod_facefusion_worker as worker
from services.live_media.runpod_facefusion_worker import (
    _authorize,
    _check_owner,
    app,
    build_facefusion_command,
    supports_video_dimensions,
)


def test_worker_command_pins_the_permissive_face_model_and_uses_argument_list():
    source = Path("/tmp/face;not-a-command.jpg")
    target = Path("/tmp/target video.mp4")
    output = Path("/tmp/output.mp4")

    command = build_facefusion_command(source, target, output)

    assert "ghost_1_256" in command
    assert "cuda" in command
    assert "--face-selector-mode" in command
    assert str(source) in command
    source_index = command.index("--source-paths")
    assert command[source_index + 1] == str(source)


def test_worker_authentication_fails_closed(monkeypatch):
    monkeypatch.delenv("SELDRUNE_FACESWAP_WORKER_TOKEN", raising=False)
    with pytest.raises(HTTPException) as not_configured:
        _authorize("Bearer anything")
    assert not_configured.value.status_code == 503

    monkeypatch.setenv("SELDRUNE_FACESWAP_WORKER_TOKEN", "expected-worker-token")
    with pytest.raises(HTTPException) as rejected:
        _authorize("Bearer wrong-token")
    assert rejected.value.status_code == 401
    _authorize("Bearer expected-worker-token")


def test_worker_job_endpoint_rejects_missing_auth_before_accepting_media(monkeypatch):
    monkeypatch.setenv("SELDRUNE_FACESWAP_WORKER_TOKEN", "expected-worker-token")
    client = TestClient(app)
    response = client.post(
        "/v1/jobs",
        data={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "user_id": "00000000-0000-0000-0000-000000000002",
            "consent_confirmed": "true",
            "synthetic_media_indicator_enabled": "true",
        },
        files={
            "source_face": ("face.jpg", b"face", "image/jpeg"),
            "target_video": ("video.mp4", b"video", "video/mp4"),
        },
    )
    assert response.status_code == 401


def test_worker_job_is_bound_to_organization_and_user():
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    job = {"organization_id": org_id, "user_id": user_id}
    _check_owner(job, org_id, user_id)
    with pytest.raises(HTTPException) as rejected:
        _check_owner(job, "00000000-0000-0000-0000-000000000003", user_id)
    assert rejected.value.status_code == 404


def test_worker_accepts_portrait_1080p_and_rejects_larger_video():
    assert supports_video_dimensions(1080, 1920)
    assert supports_video_dimensions(1920, 1080)
    assert not supports_video_dimensions(1080, 2160)
    assert not supports_video_dimensions(3840, 2160)


@pytest.mark.parametrize(
    ("failing_call", "stage", "arbitrary_exception"),
    [
        (1, "face_swap", False),
        (2, "synthetic_label", False),
        (3, "output_probe", False),
        (1, "face_swap", True),
    ],
)
def test_processing_failure_logs_only_safe_diagnostics_and_returns_generic_error(
    monkeypatch, tmp_path, caplog, failing_call, stage, arbitrary_exception
):
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    job_id = "a" * 32
    secret = "test-only-private-token"
    source = tmp_path / "private-source.png"
    target = tmp_path / "private-target.mp4"
    private_media = b"private-media-bytes"
    source.write_bytes(private_media)
    target.write_bytes(private_media)
    unsafe = f"Bearer {secret} {org_id} {user_id} {source} {target} {private_media!r}"
    monkeypatch.setenv("SELDRUNE_FACESWAP_WORKER_TOKEN", secret)
    monkeypatch.setattr(worker, "FACEFUSION_ROOT", tmp_path)
    monkeypatch.setattr(worker, "GPU_SLOT", asyncio.Semaphore(1))
    monkeypatch.setattr(
        worker,
        "JOBS",
        {
            job_id: {
                "job_id": job_id,
                "work_dir": str(tmp_path),
                "source_path": str(source),
                "target_path": str(target),
                "organization_id": org_id,
                "user_id": user_id,
            }
        },
    )
    calls = 0

    async def subprocess(*command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failing_call:
            if arbitrary_exception:
                raise ValueError(unsafe)
            return SimpleNamespace(returncode=17, communicate=AsyncMock(return_value=(
                unsafe.encode(), None
            )))
        output_path = (
            command[command.index("--output-path") + 1]
            if "--output-path" in command else command[-1]
        )
        Path(output_path).write_bytes(private_media)
        return SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"", None)))

    monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", subprocess)
    with caplog.at_level(logging.ERROR, logger=worker.__name__):
        asyncio.run(worker._process_job(job_id))

    records = [r for r in caplog.records if r.name == worker.__name__]
    assert len(records) == 1
    expected = {
        "stage": stage,
        "exception_class": "ValueError" if arbitrary_exception else "_CommandError",
    }
    if not arbitrary_exception:
        expected["returncode"] = 17
    assert json.loads(records[0].getMessage()) == expected
    assert records[0].exc_info is None
    assert records[0].stack_info is None
    serialized = repr(records[0].__dict__)
    for forbidden in (secret, org_id, user_id, job_id, str(source), str(target),
                      private_media.decode(), "facefusion.py", "--source-paths", "Bearer"):
        assert forbidden not in serialized

    response = TestClient(app).get(
        f"/v1/jobs/{job_id}",
        params={"organization_id": org_id, "user_id": user_id},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "job_id": job_id,
        "status": "failed",
        "error": "The worker could not complete this face-swap job.",
    }
