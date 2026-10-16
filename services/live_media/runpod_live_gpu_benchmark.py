"""One-shot synthetic frame benchmark for the production FaceFusion live adapter.

This module is not the worker entrypoint and adds no HTTP route. Operators may
run it explicitly on a disposable GPU Pod to measure warmed, per-frame adapter
latency with an authorized synthetic fixture.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from uuid import uuid4

_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_VIDEO_BYTES = 2 * 1024 * 1024
_MAX_VIDEO_FRAMES = 120
_WARMUP_FRAMES = 5
_REQUIRED_WIDTH = 1920
_REQUIRED_HEIGHT = 1080
_REQUIRED_FPS = 30.0


class BenchmarkInputError(ValueError):
    """An input did not meet the synthetic benchmark contract."""


def require_synthetic_authorization(environment: dict[str, str]) -> None:
    """Require both affirmative test flags before decoding or processing media."""
    if environment.get("SELDRUNE_BENCH_CONSENT_CONFIRMED") != "true":
        raise BenchmarkInputError("consent flag is required")
    if environment.get("SELDRUNE_BENCH_SYNTHETIC_MEDIA_INDICATOR_ENABLED") != "true":
        raise BenchmarkInputError("synthetic-media flag is required")


def summarize_latencies(latencies_ms: list[float], input_fps: float) -> dict[str, float | int]:
    """Return fixed, content-free per-frame timing metrics."""
    if not latencies_ms or input_fps <= 0:
        raise BenchmarkInputError("frame timing sample is empty")
    ordered = sorted(latencies_ms)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))
    deadline_ms = 1000.0 / input_fps
    mean_latency_ms = statistics.fmean(latencies_ms)
    return {
        "mean_latency_ms": round(mean_latency_ms, 3),
        "p50_latency_ms": round(statistics.median(ordered), 3),
        "p95_latency_ms": round(ordered[p95_index], 3),
        "sustainable_fps": round(1000.0 / mean_latency_ms, 3),
        "frame_deadline_ms": round(deadline_ms, 3),
        "deadline_miss_count": sum(value > deadline_ms for value in latencies_ms),
    }


def _decode_environment_payload(name: str, limit: int) -> bytes:
    encoded = os.environ.pop(name, "")
    if not encoded:
        raise BenchmarkInputError("synthetic benchmark media is missing")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise BenchmarkInputError("synthetic benchmark media is invalid") from exc
    if not payload or len(payload) > limit:
        raise BenchmarkInputError("synthetic benchmark media is outside size limits")
    return payload


def _read_video_frames(video_bytes: bytes):
    import cv2

    with tempfile.NamedTemporaryFile(suffix=".mp4") as video_file:
        video_file.write(video_bytes)
        video_file.flush()
        capture = cv2.VideoCapture(video_file.name)
        try:
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if (
                (width, height) != (_REQUIRED_WIDTH, _REQUIRED_HEIGHT)
                or abs(fps - _REQUIRED_FPS) > 0.01
                or not 1 <= frame_count <= _MAX_VIDEO_FRAMES
            ):
                raise BenchmarkInputError("video metadata is outside benchmark limits")

            frames: list[bytes] = []
            while len(frames) < frame_count:
                success, frame = capture.read()
                if not success:
                    break
                encoded, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
                if not encoded:
                    raise BenchmarkInputError("video frame encoding failed")
                frames.append(buffer.tobytes())
            if len(frames) != frame_count:
                raise BenchmarkInputError("video frame count does not match metadata")
            return width, height, fps, frames
        finally:
            capture.release()


async def _run_benchmark() -> dict[str, object]:
    import numpy as np
    import torch
    from PIL import Image

    from . import facefusion_live_adapter

    environment = os.environ
    require_synthetic_authorization(environment)
    source_bytes = _decode_environment_payload(
        "SELDRUNE_BENCH_SOURCE_FACE_B64", _MAX_SOURCE_BYTES
    )
    video_bytes = _decode_environment_payload(
        "SELDRUNE_BENCH_TARGET_VIDEO_B64", _MAX_VIDEO_BYTES
    )
    try:
        with Image.open(io.BytesIO(source_bytes)) as source_image:
            if source_image.format not in {"JPEG", "PNG", "WEBP"}:
                raise BenchmarkInputError("source image type is unsupported")
            source_image.verify()
    except (OSError, ValueError) as exc:
        raise BenchmarkInputError("source image is invalid") from exc

    width, height, input_fps, frames = _read_video_frames(video_bytes)
    with tempfile.TemporaryDirectory(prefix="seldrune-live-benchmark-") as root:
        root_path = Path(root)
        profile_id = uuid4().hex
        profile_directory = root_path / profile_id
        profile_directory.mkdir()
        (profile_directory / "face.png").write_bytes(source_bytes)
        environment["SELDRUNE_LIVE_PROFILE_ROOT"] = str(root_path)

        warmup_started = time.perf_counter()
        await facefusion_live_adapter.prepare_profile(profile_id)
        metadata = {"width": width, "height": height, "pixel_format": "jpeg"}
        for payload in frames[: min(_WARMUP_FRAMES, len(frames))]:
            await facefusion_live_adapter.transform_face(
                payload, profile_id, media_metadata=metadata
            )
        warmup_seconds = time.perf_counter() - warmup_started

        latencies_ms: list[float] = []
        changed_frames = 0
        measured_started = time.perf_counter()
        for payload in frames:
            frame_started = time.perf_counter()
            transformed_payload = await facefusion_live_adapter.transform_face(
                payload, profile_id, media_metadata=metadata
            )
            latencies_ms.append((time.perf_counter() - frame_started) * 1000.0)
            with Image.open(io.BytesIO(payload)) as original_image:
                original = np.asarray(original_image.convert("RGB"))
            with Image.open(io.BytesIO(transformed_payload)) as transformed_image:
                transformed = np.asarray(transformed_image.convert("RGB"))
            if transformed.shape != original.shape:
                raise BenchmarkInputError("transformed frame geometry changed")
            pixel_difference = np.mean(
                np.abs(original.astype(np.int16) - transformed.astype(np.int16))
            )
            if float(pixel_difference) > 1.0:
                changed_frames += 1
        measured_seconds = time.perf_counter() - measured_started

        gpu_name = torch.cuda.get_device_name(0)
        memory_gib = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        result: dict[str, object] = {
            "status": "complete",
            "benchmark": "warmed_facefusion_live_adapter",
            "model": "ghost_1_256",
            "gpu": gpu_name,
            "gpu_memory_gib": round(memory_gib, 2),
            "resolution": f"{width}x{height}",
            "input_fps": input_fps,
            "measured_frames": len(latencies_ms),
            "warmup_frames": min(_WARMUP_FRAMES, len(frames)),
            "warmup_seconds": round(warmup_seconds, 3),
            "measured_seconds": round(measured_seconds, 3),
            "changed_frames": changed_frames,
            **summarize_latencies(latencies_ms, input_fps),
        }
        return result


def main() -> None:
    """Run once, suppress dependency output, and emit only fixed JSON metrics."""
    result: dict[str, object]
    exit_code = 0
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    with open(os.devnull, "w", encoding="utf-8") as sink:
        try:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            try:
                result = asyncio.run(_run_benchmark())
            except BenchmarkInputError:
                result = {"status": "failed", "failure_code": "invalid_benchmark_input"}
                exit_code = 2
            except Exception:
                result = {"status": "failed", "failure_code": "live_adapter_error"}
                exit_code = 1
        finally:
            os.dup2(stdout_fd, 1)
            os.dup2(stderr_fd, 2)
            os.close(stdout_fd)
            os.close(stderr_fd)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
