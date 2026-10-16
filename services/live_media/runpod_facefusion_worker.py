"""Authenticated asynchronous FaceFusion worker for RunPod RTX GPUs.

The worker handles mobile video jobs over HTTPS. It preserves the source audio,
re-encodes it to AAC at 48 kHz, and burns a synthetic-media label into the video.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import shutil
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

MAX_FACE_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 75 * 1024 * 1024
MAX_VIDEO_SECONDS = 30.0
MAX_VIDEO_PIXELS = 1920 * 1080
MAX_VIDEO_DIMENSION = 1920
MAX_ACTIVE_JOBS = 2
JOB_TTL_SECONDS = 3600
JOB_TIMEOUT_SECONDS = 1800
DATA_ROOT = Path(os.getenv("SELDRUNE_RUNPOD_JOB_DIR", "/workspace/seldrune-faceswap-jobs"))
FACEFUSION_ROOT = Path(os.getenv("FACEFUSION_ROOT", "/opt/facefusion"))
JOBS: dict[str, dict[str, object]] = {}
GPU_SLOT = asyncio.Semaphore(1)
logger = logging.getLogger(__name__)
FAILURE_CODES = frozenset({
    "model_download", "model_load", "invalid_arguments", "no_source_face",
    "cuda_runtime", "input_decode", "output_encode", "unknown",
    "dependency_runtime", "filesystem", "processor_load", "python_runtime", "empty_output",
    "python_attribute", "python_type", "python_value", "python_key", "python_index",
    "python_name", "python_assertion", "python_memory",
    "python_value_facefusion", "python_value_numpy", "python_value_opencv",
    "python_value_onnxruntime", "python_value_facefusion_inference",
    "python_value_facefusion_detector", "python_value_facefusion_landmarker",
    "python_value_facefusion_geometry", "python_value_facefusion_vision",
    "python_value_facefusion_swapper", "python_value_facefusion_processor_loader",
    "python_value_facefusion_core", "python_value_facefusion_creator",
    "python_value_facefusion_selector", "python_value_facefusion_store",
    "python_value_facefusion_masker", "python_value_facefusion_recognizer",
    "python_value_facefusion_classifier", "python_value_facefusion_content",
    "python_value_facefusion_process_manager", "python_value_facefusion_video_manager",
    "python_value_facefusion_video_workflow", "python_value_facefusion_workflow_core",
    "python_value_facefusion_cli", "python_value_facefusion_audio",
    "python_value_facefusion_model_assets", "python_value_facefusion_media",
    "python_value_facefusion_tracker", "python_value_facefusion_processors",
    "python_value_facefusion_workflows", "python_value_facefusion_jobs",
    "python_value_facefusion_app_context", "python_value_facefusion_benchmarker",
    "python_value_facefusion_common_helper", "python_value_facefusion_conda",
    "python_value_facefusion_config", "python_value_facefusion_curl_builder",
    "python_value_facefusion_execution", "python_value_facefusion_exit_helper",
    "python_value_facefusion_json", "python_value_facefusion_logger",
    "python_value_facefusion_metadata", "python_value_facefusion_normalizer",
    "python_value_facefusion_sanitizer", "python_value_facefusion_state_manager",
    "python_value_facefusion_thread_helper", "python_value_facefusion_time_helper",
    "python_value_facefusion_translator", "python_value_facefusion_types",
})


def _classify_value_error_origin(output: bytes) -> str:
    """Map only the innermost recognized Python module to a fixed code.

    Traceback paths are inspected transiently. They are never retained, logged,
    or returned. The category narrows the failing runtime layer; it does not
    claim a root cause.
    """
    traceback_start = output.rfind(b"Traceback (most recent call last):")
    terminal_traceback = output[traceback_start:] if traceback_start >= 0 else output
    source_paths = re.findall(
        rb'^\s*File "([^"\r\n]+)", line [0-9]+', terminal_traceback, re.MULTILINE
    )
    facefusion_components = (
        (
            rb"(?:^|/)facefusion/processors/modules/face_swapper/core\.py$",
            "python_value_facefusion_swapper",
        ),
        (rb"(?:^|/)facefusion/core\.py$", "python_value_facefusion_core"),
        (rb"(?:^|/)facefusion/face_creator\.py$", "python_value_facefusion_creator"),
        (rb"(?:^|/)facefusion/face_selector\.py$", "python_value_facefusion_selector"),
        (rb"(?:^|/)facefusion/face_store\.py$", "python_value_facefusion_store"),
        (rb"(?:^|/)facefusion/face_masker\.py$", "python_value_facefusion_masker"),
        (rb"(?:^|/)facefusion/face_recognizer\.py$", "python_value_facefusion_recognizer"),
        (rb"(?:^|/)facefusion/face_classifier\.py$", "python_value_facefusion_classifier"),
        (rb"(?:^|/)facefusion/content_analyser\.py$", "python_value_facefusion_content"),
        (
            rb"(?:^|/)facefusion/process_manager\.py$",
            "python_value_facefusion_process_manager",
        ),
        (
            rb"(?:^|/)facefusion/video_manager\.py$",
            "python_value_facefusion_video_manager",
        ),
        (
            rb"(?:^|/)facefusion/workflows/(?:image_to_video|to_video)\.py$",
            "python_value_facefusion_video_workflow",
        ),
        (
            rb"(?:^|/)facefusion/workflows/core\.py$",
            "python_value_facefusion_workflow_core",
        ),
        (rb"(?:^|/)facefusion/inference_manager\.py$", "python_value_facefusion_inference"),
        (rb"(?:^|/)facefusion/face_detector\.py$", "python_value_facefusion_detector"),
        (rb"(?:^|/)facefusion/face_landmarker\.py$", "python_value_facefusion_landmarker"),
        (rb"(?:^|/)facefusion/face_helper\.py$", "python_value_facefusion_geometry"),
        (rb"(?:^|/)facefusion/vision\.py$", "python_value_facefusion_vision"),
        (rb"(?:^|/)facefusion/processors/core\.py$", "python_value_facefusion_processor_loader"),
        (
            rb"(?:^|/)facefusion/processors/modules/face_swapper/",
            "python_value_facefusion_swapper",
        ),
        (rb"(?:^|/)facefusion/processors/", "python_value_facefusion_processors"),
        (rb"(?:^|/)facefusion/workflows/", "python_value_facefusion_workflows"),
        (rb"(?:^|/)facefusion/jobs/", "python_value_facefusion_jobs"),
        (rb"(?:^|/)facefusion/app_context\.py$", "python_value_facefusion_app_context"),
        (rb"(?:^|/)facefusion/benchmarker\.py$", "python_value_facefusion_benchmarker"),
        (rb"(?:^|/)facefusion/common_helper\.py$", "python_value_facefusion_common_helper"),
        (rb"(?:^|/)facefusion/conda\.py$", "python_value_facefusion_conda"),
        (rb"(?:^|/)facefusion/config\.py$", "python_value_facefusion_config"),
        (rb"(?:^|/)facefusion/curl_builder\.py$", "python_value_facefusion_curl_builder"),
        (rb"(?:^|/)facefusion/execution\.py$", "python_value_facefusion_execution"),
        (rb"(?:^|/)facefusion/exit_helper\.py$", "python_value_facefusion_exit_helper"),
        (rb"(?:^|/)facefusion/json\.py$", "python_value_facefusion_json"),
        (rb"(?:^|/)facefusion/logger\.py$", "python_value_facefusion_logger"),
        (rb"(?:^|/)facefusion/metadata\.py$", "python_value_facefusion_metadata"),
        (rb"(?:^|/)facefusion/normalizer\.py$", "python_value_facefusion_normalizer"),
        (rb"(?:^|/)facefusion/sanitizer\.py$", "python_value_facefusion_sanitizer"),
        (rb"(?:^|/)facefusion/state_manager\.py$", "python_value_facefusion_state_manager"),
        (rb"(?:^|/)facefusion/thread_helper\.py$", "python_value_facefusion_thread_helper"),
        (rb"(?:^|/)facefusion/time_helper\.py$", "python_value_facefusion_time_helper"),
        (rb"(?:^|/)facefusion/translator\.py$", "python_value_facefusion_translator"),
        (rb"(?:^|/)facefusion/types\.py$", "python_value_facefusion_types"),
        (
            rb"(?:^|/)facefusion/(?:args|choices|cli_helper|program|program_helper)\.py$",
            "python_value_facefusion_cli",
        ),
        (rb"(?:^|/)facefusion\.py$", "python_value_facefusion_cli"),
        (rb"(?:^|/)facefusion/(?:audio|voice_extractor)\.py$", "python_value_facefusion_audio"),
        (
            rb"(?:^|/)facefusion/(?:download|hash_helper|model_helper)\.py$",
            "python_value_facefusion_model_assets",
        ),
        (
            rb"(?:^|/)facefusion/(?:ffmpeg|ffmpeg_builder|ffprobe|ffprobe_builder|"
            rb"frame_store|filesystem|temp_helper)\.py$",
            "python_value_facefusion_media",
        ),
        (rb"(?:^|/)facefusion/face_tracker\.py$", "python_value_facefusion_tracker"),
    )
    for source_path in reversed(source_paths):
        for pattern, code in facefusion_components:
            if re.search(pattern, source_path):
                return code
        if re.search(rb"(?:^|/)facefusion/", source_path):
            return "python_value_facefusion"
        if re.search(rb"(?:^|/)numpy/", source_path):
            return "python_value_numpy"
        if re.search(rb"(?:^|/)cv2(?:/|_)", source_path):
            return "python_value_opencv"
        if re.search(rb"(?:^|/)onnxruntime(?:/|_)", source_path):
            return "python_value_onnxruntime"
    return "python_value"


def _classify_command_failure(output: bytes) -> str:
    """Classify transient output; retain no text, paths, or captures.

    Messages come from pinned FaceFusion locales/download/inference code,
    argparse and ONNX Runtime. A category is evidence of a message, not proof
    of its underlying cause. Unrecognized failures remain unknown.
    """
    patterns = (
        ("dependency_runtime", rb"(?:modulenotfounderror:|importerror:|"
                               rb"error while loading shared libraries:)"),
        ("filesystem", rb"(?:permissionerror:|filenotfounderror:|"
                       rb"can't open file [^\r\n]*\[errno [^\r\n]+)"),
        ("processor_load",
         rb"processor [^\r\n]+ (?:could not be loaded|not implemented correctly)"),
        ("invalid_arguments",
         rb"error: (?:unrecognized arguments:|argument [^\r\n]*invalid choice:)"),
        ("no_source_face", rb"no source face detected"),
        ("cuda_runtime", rb"(?:cuda failure|cuda error|failed to create cudaexecutionprovider|"
                         rb"failed to load library [^\r\n]*libonnxruntime_providers_cuda)"),
        ("model_download", rb"validating (?:hash|source) for [^\r\n]+ failed"),
        ("model_load", rb"loading model [^\r\n]+ failed"),
        ("input_decode", rb"(?:choose an image for the source|"
                         rb"choose an image or video for the target|"
                         rb"extracting frames failed|temporary frames not found)"),
        ("output_encode", rb"(?:merging video failed|processing to video failed)"),
    )
    for code, pattern in patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return code
    if b"Traceback (most recent call last):" in output:
        # Match Python's terminal exception lines, not arbitrary words in frames
        # or messages. Chained tracebacks use the final terminal exception;
        # an unrecognized outer exception must not inherit an inner category.
        # Only fixed built-in types are mapped; never retain a match or message.
        exception_codes = {
            b"AttributeError": "python_attribute",
            b"TypeError": "python_type",
            b"ValueError": "python_value",
            b"KeyError": "python_key",
            b"IndexError": "python_index",
            b"NameError": "python_name",
            b"UnboundLocalError": "python_name",
            b"AssertionError": "python_assertion",
            b"MemoryError": "python_memory",
            b"RuntimeError": "python_runtime",
        }
        for line in reversed(output.splitlines()):
            exception_type = line.partition(b":")[0]
            if re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_.]*", exception_type):
                code = exception_codes.get(exception_type, "python_runtime")
                if code == "python_value":
                    return _classify_value_error_origin(output)
                return code
        return "python_runtime"
    if not output.strip():
        return "empty_output"
    return "unknown"


class _CommandError(RuntimeError):
    """Preserve only the exit code, never the command or captured output."""

    def __init__(
        self, message: str, returncode: int | None, failure_code: str = "unknown"
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.failure_code = failure_code if failure_code in FAILURE_CODES else "unknown"


async def _cleanup_expired_jobs() -> None:
    while True:
        await asyncio.sleep(60)
        _prune_expired_jobs()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    cleanup_task = asyncio.create_task(_cleanup_expired_jobs())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Seldrune RunPod FaceSwap Worker",
    docs_url=None,
    redoc_url=None,
    lifespan=_lifespan,
)


def _authorize(authorization: str | None) -> None:
    expected_token = os.getenv("SELDRUNE_FACESWAP_WORKER_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="Worker authentication is not configured.")
    expected = f"Bearer {expected_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Worker authentication failed.")


def _owner_values(organization_id: str, user_id: str) -> tuple[str, str]:
    try:
        return str(UUID(organization_id)), str(UUID(user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid job owner.") from exc


def _validate_extension(filename: str | None, allowed: set[str], label: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported {label} file type.")
    return suffix


async def _read_limited(upload: UploadFile, limit: int, label: str) -> bytes:
    data = await upload.read(limit + 1)
    if not data:
        raise HTTPException(status_code=422, detail=f"The {label} file is empty.")
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"The {label} file is too large.")
    return data


def build_facefusion_command(
    source_path: Path, target_path: Path, output_path: Path
) -> list[str]:
    """Build a fixed FaceFusion invocation without shell interpretation."""
    return [
        sys.executable,
        "facefusion.py",
        "headless-run",
        "--processors",
        "face_swapper",
        "--face-swapper-model",
        "ghost_1_256",
        "--face-selector-mode",
        "one",
        "--execution-providers",
        "cuda",
        "--execution-device-ids",
        "0",
        "--video-memory-strategy",
        "strict",
        "--source-paths",
        str(source_path),
        "--target-path",
        str(target_path),
        "--output-path",
        str(output_path),
        "--output-video-encoder",
        "libx264",
        "--output-video-preset",
        "veryfast",
        "--output-video-quality",
        "85",
        "--output-audio-encoder",
        "aac",
        "--output-audio-quality",
        "92",
    ]


def _synthetic_output_command(source_path: Path, output_path: Path) -> list[str]:
    drawtext = (
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
        "text='AI-SYNTHETIC':x=18:y=18:fontcolor=white:fontsize=26:"
        "box=1:boxcolor=black@0.65:boxborderw=8"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        drawtext,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


async def _run_command(command: list[str], *, cwd: Path, timeout: float) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise _CommandError(
            "Media processing exceeded its time limit.", process.returncode
        ) from None
    if process.returncode != 0:
        raise _CommandError(
            "Media processing failed.", process.returncode, _classify_command_failure(output)
        )
    return output


async def _probe_video(path: Path) -> dict[str, object]:
    output = await _run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate,sample_rate",
            "-of",
            "json",
            str(path),
        ],
        cwd=path.parent,
        timeout=20,
    )
    try:
        return json.loads(output)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("The video metadata could not be read.") from exc


async def _runtime_ready() -> tuple[bool, str | None]:
    if not FACEFUSION_ROOT.is_dir():
        return False, None
    try:
        gpu = await _run_command(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            cwd=Path("/tmp"),
            timeout=10,
        )
        await _run_command(
            [
                sys.executable,
                "-c",
                "import onnxruntime as ort; "
                "assert 'CUDAExecutionProvider' in ort.get_available_providers()",
            ],
            cwd=FACEFUSION_ROOT,
            timeout=10,
        )
    except (OSError, RuntimeError):
        return False, None
    gpu_name = gpu.decode("utf-8", errors="ignore").strip().splitlines()
    return bool(gpu_name), gpu_name[0] if gpu_name else None


def _fraction(value: object) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    try:
        numerator, denominator = value.split("/", maxsplit=1)
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None


def supports_video_dimensions(width: int, height: int) -> bool:
    return (
        width > 0
        and height > 0
        and max(width, height) <= MAX_VIDEO_DIMENSION
        and width * height <= MAX_VIDEO_PIXELS
    )


async def _process_job(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    async with GPU_SLOT:
        job["status"] = "processing"
        job["updated_at"] = time.time()
        work_dir = Path(str(job["work_dir"]))
        source = Path(str(job["source_path"]))
        target = Path(str(job["target_path"]))
        raw_output = work_dir / "faceswapped.mp4"
        labeled_output = work_dir / "seldrune-synthetic-output.mp4"
        stage = "runtime_check"
        try:
            if not FACEFUSION_ROOT.is_dir():
                raise RuntimeError("The FaceFusion runtime is not installed.")
            stage = "face_swap"
            await _run_command(
                build_facefusion_command(source, target, raw_output),
                cwd=FACEFUSION_ROOT,
                timeout=JOB_TIMEOUT_SECONDS,
            )
            if not raw_output.is_file() or raw_output.stat().st_size == 0:
                raise RuntimeError("FaceFusion produced no output video.")
            stage = "synthetic_label"
            await _run_command(
                _synthetic_output_command(raw_output, labeled_output),
                cwd=work_dir,
                timeout=JOB_TIMEOUT_SECONDS,
            )
            if not labeled_output.is_file() or labeled_output.stat().st_size == 0:
                raise RuntimeError("The labeled output video was not created.")
            stage = "output_probe"
            metadata = await _probe_video(labeled_output)
            stage = "output_metadata"
            streams = metadata.get("streams", [])
            video_stream = next(
                (item for item in streams if item.get("codec_type") == "video"), None
            )
            audio_stream = next(
                (item for item in streams if item.get("codec_type") == "audio"), None
            )
            if not video_stream:
                raise RuntimeError("The output video stream is missing.")
            duration = float(metadata.get("format", {}).get("duration", 0.0))
            actual_accelerator = None
            try:
                gpu = await _run_command(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    cwd=work_dir,
                    timeout=10,
                )
                if "4090" in gpu.decode("utf-8", errors="ignore"):
                    actual_accelerator = "rtx-4090"
            except (OSError, RuntimeError):
                pass
            job["output_path"] = str(labeled_output)
            job["output_width"] = video_stream.get("width")
            job["output_height"] = video_stream.get("height")
            job["output_fps"] = _fraction(video_stream.get("r_frame_rate"))
            job["audio_sample_rate_hz"] = (
                int(audio_stream["sample_rate"])
                if audio_stream and audio_stream.get("sample_rate")
                else None
            )
            job["duration_seconds"] = duration
            job["actual_accelerator_profile"] = actual_accelerator
            job["audio_action"] = "original audio re-encoded to AAC at 48 kHz; no voice conversion"
            job["status"] = "completed"
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            # Deliberately omit exception text, traceback, job context and media paths.
            diagnostic: dict[str, str | int] = {
                "stage": stage,
                "exception_class": type(exc).__name__,
            }
            if isinstance(exc, _CommandError) and type(exc.returncode) is int:
                diagnostic["returncode"] = exc.returncode
            job["diagnostics"] = diagnostic.copy()
            if isinstance(exc, _CommandError):
                # Classification is available only via the authenticated owner status,
                # not the public error or internal log event.
                job["diagnostics"]["failure_code"] = exc.failure_code
            logger.error(json.dumps(diagnostic, sort_keys=True))
            job["status"] = "failed"
            job["error"] = "The worker could not complete this face-swap job."
        finally:
            job["updated_at"] = time.time()
            for upload_path in (source, target, raw_output):
                try:
                    upload_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _check_owner(job: dict[str, object], organization_id: str, user_id: str) -> None:
    org_id, owner_id = _owner_values(organization_id, user_id)
    if job.get("organization_id") != org_id or job.get("user_id") != owner_id:
        raise HTTPException(status_code=404, detail="Face-swap job not found.")


def _prune_expired_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    for job_id, job in list(JOBS.items()):
        active = job.get("status") in {"queued", "processing"}
        if float(job.get("updated_at", 0)) >= cutoff or active:
            continue
        work_dir = Path(str(job.get("work_dir", "")))
        if work_dir.is_dir():
            shutil.rmtree(work_dir, ignore_errors=True)
        JOBS.pop(job_id, None)


@app.get("/health")
async def health() -> dict[str, object]:
    ready, gpu_name = await _runtime_ready()
    return {
        "status": "ready" if ready else "not_ready",
        "engine": "facefusion",
        "accelerator": gpu_name,
        "synthetic_watermark": True,
        "audio_sample_rate_hz": 48000,
        "voice_conversion": False,
    }


@app.post("/v1/jobs", status_code=202)
async def create_job(
    source_face: Annotated[UploadFile, File()],
    target_video: Annotated[UploadFile, File()],
    organization_id: Annotated[str, Form()],
    user_id: Annotated[str, Form()],
    consent_confirmed: Annotated[bool, Form()],
    synthetic_media_indicator_enabled: Annotated[bool, Form()],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _authorize(authorization)
    org_id, owner_id = _owner_values(organization_id, user_id)
    if not consent_confirmed or not synthetic_media_indicator_enabled:
        raise HTTPException(
            status_code=422,
            detail="Authorization and the synthetic label are required.",
        )
    active_job_count = sum(
        job.get("status") in {"queued", "processing"}
        for job in JOBS.values()
    )
    if active_job_count >= MAX_ACTIVE_JOBS:
        raise HTTPException(
            status_code=429,
            detail="The GPU queue is full. Try again after a job completes.",
        )
    ready, _gpu_name = await _runtime_ready()
    if not ready:
        raise HTTPException(status_code=503, detail="The FaceSwap GPU worker is not ready.")
    face_suffix = _validate_extension(
        source_face.filename, {".jpg", ".jpeg", ".png", ".webp"}, "face image"
    )
    video_suffix = _validate_extension(
        target_video.filename, {".mp4", ".mov", ".m4v", ".webm"}, "video"
    )
    face_data = await _read_limited(source_face, MAX_FACE_BYTES, "face image")
    video_data = await _read_limited(target_video, MAX_VIDEO_BYTES, "video")
    _prune_expired_jobs()
    job_id = uuid4().hex
    work_dir = DATA_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=False)
    face_path = work_dir / f"authorized-face{face_suffix}"
    video_path = work_dir / f"target-video{video_suffix}"
    face_path.write_bytes(face_data)
    video_path.write_bytes(video_data)
    try:
        metadata = await _probe_video(video_path)
        format_info = metadata.get("format", {})
        streams = metadata.get("streams", [])
        video_stream = next(
            (item for item in streams if item.get("codec_type") == "video"), None
        )
        duration = float(format_info.get("duration", 0.0))
        if not video_stream or duration <= 0 or duration > MAX_VIDEO_SECONDS:
            raise ValueError("unsupported video duration or stream")
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        if not supports_video_dimensions(width, height):
            raise ValueError("video exceeds the supported 1080p input target")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail="Use a readable video up to 30 seconds and 1080p.",
        ) from exc
    now = time.time()
    JOBS[job_id] = {
        "job_id": job_id,
        "organization_id": org_id,
        "user_id": owner_id,
        "status": "queued",
        "work_dir": str(work_dir),
        "source_path": str(face_path),
        "target_path": str(video_path),
        "created_at": now,
        "updated_at": now,
        "synthetic_media_indicator_enabled": True,
        "model": "ghost_1_256",
        "model_license": "Apache-2.0",
    }
    asyncio.create_task(_process_job(job_id))
    return {
        "job_id": job_id,
        "status": "queued",
        "synthetic_media_indicator_enabled": True,
        "model": "ghost_1_256",
        "model_license": "Apache-2.0",
    }


@app.get("/v1/jobs/{job_id}")
async def get_job(
    job_id: str,
    organization_id: str,
    user_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _authorize(authorization)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Face-swap job not found.")
    _check_owner(job, organization_id, user_id)
    response = {
        key: job[key]
        for key in (
            "job_id",
            "status",
            "error",
            "synthetic_media_indicator_enabled",
            "model",
            "model_license",
            "output_width",
            "output_height",
            "output_fps",
            "audio_sample_rate_hz",
            "duration_seconds",
            "actual_accelerator_profile",
            "audio_action",
        )
        if key in job
    }
    diagnostic = job.get("diagnostics")
    if job.get("status") == "failed" and isinstance(diagnostic, dict):
        response["diagnostics"] = {
            key: value
            for key, value in diagnostic.items()
            if (key in {"stage", "exception_class"} and isinstance(value, str))
            or (key == "returncode" and type(value) is int)
            or (key == "failure_code" and isinstance(value, str) and value in FAILURE_CODES)
        }
    return response


@app.get("/v1/jobs/{job_id}/download")
async def download_job(
    job_id: str,
    organization_id: str,
    user_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> FileResponse:
    _authorize(authorization)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Face-swap job not found.")
    _check_owner(job, organization_id, user_id)
    if job.get("status") != "completed" or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="The face-swap job is not complete.")
    return FileResponse(
        str(job["output_path"]),
        media_type="video/mp4",
        filename="seldrune-face-swap-synthetic.mp4",
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/v1/jobs/{job_id}")
async def delete_job(
    job_id: str,
    organization_id: str,
    user_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    _authorize(authorization)
    job = JOBS.get(job_id)
    if not job:
        return {"deleted": True}
    _check_owner(job, organization_id, user_id)
    if job.get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="A running job cannot be deleted yet.")
    shutil.rmtree(Path(str(job["work_dir"])), ignore_errors=True)
    JOBS.pop(job_id, None)
    return {"deleted": True}
