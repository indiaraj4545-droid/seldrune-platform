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
    owner_diagnostic = expected if arbitrary_exception else {**expected, "failure_code": "unknown"}
    assert worker.JOBS[job_id]["diagnostics"] == owner_diagnostic
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
        "diagnostics": owner_diagnostic,
    }
    for forbidden in (secret, str(source), str(target), private_media.decode(),
                      "facefusion.py", "--source-paths", "Bearer"):
        assert forbidden not in response.text


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("owner", 200),
        ("wrong_org", 404),
        ("wrong_user", 404),
        ("missing", 404),
        ("unauthenticated", 401),
        ("completed", 200),
        ("queued", 200),
        ("processing", 200),
    ],
)
@pytest.mark.parametrize("failure_code", sorted(worker.FAILURE_CODES))
def test_status_diagnostics_require_auth_owner_and_failed_job(
    monkeypatch, scenario, expected_status, failure_code
):
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    other_id = "00000000-0000-0000-0000-000000000003"
    job_id = "a" * 32
    safe = {"stage": "face_swap", "exception_class": "_CommandError", "returncode": 17,
            "failure_code": failure_code}
    raw_detail = "private exception stderr command credentials media"
    job = {
        "job_id": job_id,
        "organization_id": org_id,
        "user_id": user_id,
        "status": scenario if scenario in {"completed", "queued", "processing"} else "failed",
        "diagnostics": {**safe, "stderr": raw_detail, "exception_text": raw_detail},
    }
    monkeypatch.setattr(worker, "JOBS", {} if scenario == "missing" else {job_id: job})
    monkeypatch.setenv("SELDRUNE_FACESWAP_WORKER_TOKEN", "test-only-token")
    response = TestClient(app).get(
        f"/v1/jobs/{job_id}",
        params={
            "organization_id": other_id if scenario == "wrong_org" else org_id,
            "user_id": other_id if scenario == "wrong_user" else user_id,
        },
        headers={} if scenario == "unauthenticated" else {
            "Authorization": "Bearer test-only-token"
        },
    )
    assert response.status_code == expected_status
    assert raw_detail not in response.text
    if scenario == "owner":
        assert response.json()["diagnostics"] == safe
    else:
        assert "diagnostics" not in response.json()
        assert "face_swap" not in response.text
        assert failure_code not in response.text
    if expected_status == 404:
        assert response.json() == {"detail": "Face-swap job not found."}


@pytest.mark.parametrize("returncode", [None, "17", True])
def test_status_diagnostics_omit_non_integer_returncodes(monkeypatch, returncode):
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    job_id = "a" * 32
    monkeypatch.setenv("SELDRUNE_FACESWAP_WORKER_TOKEN", "test-only-token")
    monkeypatch.setattr(worker, "JOBS", {job_id: {
        "organization_id": org_id,
        "user_id": user_id,
        "status": "failed",
        "diagnostics": {"stage": "face_swap", "exception_class": "ValueError",
                        "returncode": returncode},
    }})
    response = TestClient(app).get(
        f"/v1/jobs/{job_id}",
        params={"organization_id": org_id, "user_id": user_id},
        headers={"Authorization": "Bearer test-only-token"},
    )
    assert response.status_code == 200
    assert response.json()["diagnostics"] == {"stage": "face_swap", "exception_class": "ValueError"}


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (b"[FACEFUSION.DOWNLOAD] validating hash for private failed", "model_download"),
        (b"[FACEFUSION.DOWNLOAD] validating source for private failed", "model_download"),
        (b"[FACEFUSION.INFERENCE_MANAGER] loading model private failed", "model_load"),
        (b"error: argument --private: invalid choice: private", "invalid_arguments"),
        (b"error: unrecognized arguments: private", "invalid_arguments"),
        (b"[FACEFUSION.CORE] no source face detected!", "no_source_face"),
        (b"CUDA failure 999: private", "cuda_runtime"),
        (b"Failed to load library /private/libonnxruntime_providers_cuda.so", "cuda_runtime"),
        (b"[FACEFUSION.TO_VIDEO] extracting frames failed", "input_decode"),
        (b"[FACEFUSION.TO_VIDEO] merging video failed", "output_encode"),
        (b"[FACEFUSION.TO_VIDEO] processing to video failed", "output_encode"),
        (b"private arbitrary failure", "unknown"),
        (b"ModuleNotFoundError: private", "dependency_runtime"),
        (b"ImportError: private", "dependency_runtime"),
        (b"FileNotFoundError: private", "filesystem"),
        (b"PermissionError: private", "filesystem"),
        (b"[FACEFUSION.CORE] processor private could not be loaded", "processor_load"),
        (b"Traceback (most recent call last): private", "python_runtime"),
    ],
)
def test_subprocess_failure_classifies_real_upstream_messages_without_retaining_output(
    monkeypatch, tmp_path, caplog, message, code
):
    private = b"Bearer private-token /private/media secret arbitrary-exception-text"
    process = SimpleNamespace(
        returncode=1, communicate=AsyncMock(return_value=(message + b"\n" + private, None))
    )
    monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(worker._CommandError) as caught:
        asyncio.run(worker._run_command(["private-command"], cwd=tmp_path, timeout=1))
    error = caught.value
    assert error.failure_code == code
    assert error.returncode == 1
    assert str(error) == "Media processing failed."
    assert error.__dict__ == {"returncode": 1, "failure_code": code}
    assert not caplog.records


def test_owner_status_drops_unapproved_failure_code(monkeypatch):
    monkeypatch.setenv("SELDRUNE_FACESWAP_WORKER_TOKEN", "test-only-token")
    owner = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr(worker, "JOBS", {"test": {
        "organization_id": owner, "user_id": owner, "status": "failed",
        "diagnostics": {"stage": "face_swap", "failure_code": "private arbitrary details"},
    }})
    response = TestClient(app).get(
        "/v1/jobs/test", params={"organization_id": owner, "user_id": owner},
        headers={"Authorization": "Bearer test-only-token"},
    )
    assert response.status_code == 200
    assert response.json()["diagnostics"] == {"stage": "face_swap"}


def test_empty_subprocess_output_has_fixed_safe_category():
    assert worker._classify_command_failure(b" \n\t") == "empty_output"


@pytest.mark.parametrize(
    ("exception_type", "code"),
    [
        (AttributeError, "python_attribute"), (TypeError, "python_type"),
        (ValueError, "python_value"), (KeyError, "python_key"),
        (IndexError, "python_index"), (NameError, "python_name"),
        (UnboundLocalError, "python_name"), (AssertionError, "python_assertion"),
        (MemoryError, "python_memory"), (RuntimeError, "python_runtime"),
    ],
)
def test_python_exception_type_classification_never_retains_traceback(
    monkeypatch, tmp_path, caplog, exception_type, code
):
    import traceback

    private = "Bearer private-token /private/media arbitrary-secret-detail"
    try:
        raise exception_type(private)
    except exception_type:
        # A synthetic local traceback only; never read a real job's raw output.
        transient = traceback.format_exc().encode()
    process = SimpleNamespace(
        returncode=1, communicate=AsyncMock(return_value=(transient, None))
    )
    monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(worker._CommandError) as caught:
        asyncio.run(worker._run_command(["private-command"], cwd=tmp_path, timeout=1))
    assert caught.value.__dict__ == {"returncode": 1, "failure_code": code}
    assert str(caught.value) == "Media processing failed."
    assert not caplog.records


def test_python_exception_classification_uses_last_terminal_type_only():
    trace = (
        b"Traceback (most recent call last):\nValueError: private\n"
        b"During handling of the above exception, another exception occurred:\n"
        b"Traceback (most recent call last):\n"
        b"  private frame mentions AttributeError: private\nTypeError: private\n"
    )
    assert worker._classify_command_failure(trace) == "python_type"
    assert worker._classify_command_failure(b"TypeError: private") == "unknown"
    assert worker._classify_command_failure(
        b"Traceback (most recent call last):\n  private frame TypeError: private\n"
        b"CustomError: private"
    ) == "python_runtime"
    assert worker._classify_command_failure(
        b"Traceback (most recent call last):\nValueError: private\n"
        b"Traceback (most recent call last):\nCustomError: private"
    ) == "python_runtime"


@pytest.mark.parametrize(
    ("frame_path", "code"),
    [
        (b"/opt/facefusion/facefusion/core.py", "python_value_facefusion_core"),
        (b"/opt/facefusion/facefusion/face_creator.py", "python_value_facefusion_creator"),
        (b"/opt/facefusion/facefusion/face_selector.py", "python_value_facefusion_selector"),
        (b"/opt/facefusion/facefusion/face_store.py", "python_value_facefusion_store"),
        (b"/opt/facefusion/facefusion/face_masker.py", "python_value_facefusion_masker"),
        (
            b"/opt/facefusion/facefusion/face_recognizer.py",
            "python_value_facefusion_recognizer",
        ),
        (
            b"/opt/facefusion/facefusion/face_classifier.py",
            "python_value_facefusion_classifier",
        ),
        (
            b"/opt/facefusion/facefusion/content_analyser.py",
            "python_value_facefusion_content",
        ),
        (
            b"/opt/facefusion/facefusion/process_manager.py",
            "python_value_facefusion_process_manager",
        ),
        (
            b"/opt/facefusion/facefusion/video_manager.py",
            "python_value_facefusion_video_manager",
        ),
        (
            b"/opt/facefusion/facefusion/workflows/to_video.py",
            "python_value_facefusion_video_workflow",
        ),
        (
            b"/opt/facefusion/facefusion/workflows/core.py",
            "python_value_facefusion_workflow_core",
        ),
        (
            b"/opt/facefusion/facefusion/processors/modules/face_swapper/core.py",
            "python_value_facefusion_swapper",
        ),
        (
            b"/opt/facefusion/facefusion/inference_manager.py",
            "python_value_facefusion_inference",
        ),
        (
            b"/opt/facefusion/facefusion/face_detector.py",
            "python_value_facefusion_detector",
        ),
        (
            b"/opt/facefusion/facefusion/face_landmarker.py",
            "python_value_facefusion_landmarker",
        ),
        (
            b"/opt/facefusion/facefusion/face_helper.py",
            "python_value_facefusion_geometry",
        ),
        (
            b"/opt/facefusion/facefusion/vision.py",
            "python_value_facefusion_vision",
        ),
        (
            b"/opt/facefusion/facefusion/processors/core.py",
            "python_value_facefusion_processor_loader",
        ),
        (
            b"/opt/facefusion/facefusion/processors/modules/face_swapper/choices.py",
            "python_value_facefusion_swapper",
        ),
        (
            b"/opt/facefusion/facefusion/processors/modules/face_detector/core.py",
            "python_value_facefusion_processors",
        ),
        (
            b"/opt/facefusion/facefusion/workflows/image_to_image.py",
            "python_value_facefusion_workflows",
        ),
        (
            b"/opt/facefusion/facefusion/jobs/job_runner.py",
            "python_value_facefusion_jobs",
        ),
        (b"/opt/facefusion/facefusion/app_context.py", "python_value_facefusion_app_context"),
        (b"/opt/facefusion/facefusion/benchmarker.py", "python_value_facefusion_benchmarker"),
        (
            b"/opt/facefusion/facefusion/common_helper.py",
            "python_value_facefusion_common_helper",
        ),
        (b"/opt/facefusion/facefusion/conda.py", "python_value_facefusion_conda"),
        (b"/opt/facefusion/facefusion/config.py", "python_value_facefusion_config"),
        (
            b"/opt/facefusion/facefusion/curl_builder.py",
            "python_value_facefusion_curl_builder",
        ),
        (b"/opt/facefusion/facefusion/execution.py", "python_value_facefusion_execution"),
        (
            b"/opt/facefusion/facefusion/exit_helper.py",
            "python_value_facefusion_exit_helper",
        ),
        (b"/opt/facefusion/facefusion/json.py", "python_value_facefusion_json"),
        (b"/opt/facefusion/facefusion/logger.py", "python_value_facefusion_logger"),
        (b"/opt/facefusion/facefusion/metadata.py", "python_value_facefusion_metadata"),
        (
            b"/opt/facefusion/facefusion/normalizer.py",
            "python_value_facefusion_normalizer",
        ),
        (b"/opt/facefusion/facefusion/sanitizer.py", "python_value_facefusion_sanitizer"),
        (
            b"/opt/facefusion/facefusion/state_manager.py",
            "python_value_facefusion_state_manager",
        ),
        (
            b"/opt/facefusion/facefusion/thread_helper.py",
            "python_value_facefusion_thread_helper",
        ),
        (
            b"/opt/facefusion/facefusion/time_helper.py",
            "python_value_facefusion_time_helper",
        ),
        (b"/opt/facefusion/facefusion/translator.py", "python_value_facefusion_translator"),
        (b"/opt/facefusion/facefusion/types.py", "python_value_facefusion_types"),
        (b"/opt/facefusion/facefusion/program.py", "python_value_facefusion_cli"),
        (b"/opt/facefusion/facefusion.py", "python_value_facefusion_cli"),
        (b"/opt/facefusion/facefusion/audio.py", "python_value_facefusion_audio"),
        (
            b"/opt/facefusion/facefusion/model_helper.py",
            "python_value_facefusion_model_assets",
        ),
        (b"/opt/facefusion/facefusion/ffmpeg.py", "python_value_facefusion_media"),
        (
            b"/opt/facefusion/facefusion/frame_store.py",
            "python_value_facefusion_media",
        ),
        (
            b"/opt/facefusion/facefusion/face_tracker.py",
            "python_value_facefusion_tracker",
        ),
        (
            b"/usr/local/lib/python3.12/site-packages/numpy/_core/fromnumeric.py",
            "python_value_numpy",
        ),
        (b"/usr/local/lib/python3.12/site-packages/cv2/__init__.py", "python_value_opencv"),
        (
            b"/usr/local/lib/python3.12/site-packages/onnxruntime/capi/collection.py",
            "python_value_onnxruntime",
        ),
        (b"/private/runtime/library.py", "python_value"),
    ],
)
def test_python_value_origin_uses_fixed_codes_without_retaining_paths_or_text(
    monkeypatch, tmp_path, caplog, frame_path, code
):
    trace = (
        b'Traceback (most recent call last):\n  File "'
        + frame_path
        + b'", line 42, in private_frame\nValueError: private media path and token\n'
    )
    process = SimpleNamespace(returncode=1, communicate=AsyncMock(return_value=(trace, None)))
    monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))

    with pytest.raises(worker._CommandError) as caught:
        asyncio.run(worker._run_command(["private-command"], cwd=tmp_path, timeout=1))

    assert caught.value.__dict__ == {"returncode": 1, "failure_code": code}
    assert str(caught.value) == "Media processing failed."
    assert not caplog.records


def test_python_value_origin_uses_only_the_terminal_chained_traceback():
    trace = (
        b'Traceback (most recent call last):\n  File "/site-packages/numpy/core.py", line 1\n'
        b"ValueError: private inner detail\n"
        b"During handling of the above exception, another exception occurred:\n"
        b'Traceback (most recent call last):\n  File "/private/other/runtime.py", line 2\n'
        b"ValueError: private outer detail\n"
    )

    assert worker._classify_command_failure(trace) == "python_value"
