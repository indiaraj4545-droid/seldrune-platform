"""CUDA FaceFusion adapter for authorized, disclosed LiveShell face profiles."""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

from PIL import Image

from .live_profile_store import resolve_face_reference

_FACEFUSION_ROOT = Path(os.getenv("FACEFUSION_ROOT", "/opt/facefusion")).resolve()
_ALLOWED_MODEL = "ghost_1_256"
_LOCK = asyncio.Lock()
_ACTIVE_PROFILE: str | None = None
_INITIALIZED = False


def _ensure_import_path() -> None:
    if not _FACEFUSION_ROOT.is_dir():
        raise RuntimeError("FaceFusion runtime is not installed")
    root = str(_FACEFUSION_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _initialize(profile_path: Path) -> None:
    global _INITIALIZED, _ACTIVE_PROFILE
    _ensure_import_path()

    from facefusion.args import apply_args
    from facefusion.processors.core import load_processor_module
    from facefusion.program import create_program
    from facefusion import state_manager

    if not _INITIALIZED:
        output_placeholder = profile_path.parent / "unused-live-output.jpg"
        previous_cwd = Path.cwd()
        os.chdir(_FACEFUSION_ROOT)
        try:
            args = vars(
                create_program().parse_args(
                    [
                    "headless-run",
                    "--source-paths",
                    str(profile_path),
                    "--target-path",
                    str(profile_path),
                    "--output-path",
                    str(output_placeholder),
                    "--processors",
                    "face_swapper",
                    "--face-swapper-model",
                    _ALLOWED_MODEL,
                    "--face-selector-mode",
                    "one",
                    "--execution-providers",
                    "cuda",
                    "--execution-device-ids",
                    "0",
                    "--execution-thread-count",
                    "2",
                    "--video-memory-strategy",
                    "moderate",
                    "--log-level",
                    "error",
                    ]
                )
            )
            apply_args(args, state_manager.init_item)
        finally:
            os.chdir(previous_cwd)
        _INITIALIZED = True
    else:
        state_manager.set_item("source_paths", [str(profile_path)])

    processor = load_processor_module("face_swapper")
    if not processor.pre_check() or not processor.pre_process("stream"):
        raise RuntimeError("FaceFusion live face processor is not ready")
    # Materialize ONNX Runtime sessions before the WebRTC media clock starts.
    if not processor.get_inference_pool():
        raise RuntimeError("FaceFusion live inference pool did not initialize")
    _ACTIVE_PROFILE = str(profile_path)


def _decode_jpeg_bgr(payload: bytes, width: int, height: int):
    import numpy as np

    try:
        with Image.open(io.BytesIO(payload)) as source:
            rgb = np.asarray(source.convert("RGB"))
    except OSError as exc:
        raise ValueError("live face adapter requires a decodable JPEG frame") from exc
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("live face frame must contain RGB pixels")
    actual_height, actual_width = rgb.shape[:2]
    if (actual_width, actual_height) != (width, height):
        raise ValueError("live face JPEG dimensions do not match transport metadata")
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _encode_jpeg_bgr(bgr) -> bytes:
    output = io.BytesIO()
    Image.fromarray(bgr[:, :, ::-1], mode="RGB").save(
        output,
        format="JPEG",
        quality=90,
        optimize=False,
        subsampling=1,
    )
    payload = output.getvalue()
    if not payload:
        raise RuntimeError("FaceFusion returned no encoded live frame")
    return payload


def _transform_sync(
    payload: bytes,
    profile_id: str,
    *,
    width: int,
    height: int,
) -> bytes:
    global _ACTIVE_PROFILE
    profile_path = resolve_face_reference(profile_id)
    if not _INITIALIZED or _ACTIVE_PROFILE != str(profile_path):
        _initialize(profile_path)

    from facefusion.streamer import process_stream_frame

    source = _decode_jpeg_bgr(payload, width, height)
    transformed = process_stream_frame(
        __import__("facefusion.vision", fromlist=["read_static_images"]).read_static_images(
            [str(profile_path)]
        ),
        source,
    )
    if transformed is None or getattr(transformed, "shape", None) != source.shape:
        raise RuntimeError("FaceFusion live transform changed the frame geometry")
    if transformed.dtype.name != "uint8":
        transformed = transformed.clip(0, 255).astype("uint8")
    return _encode_jpeg_bgr(transformed)


async def prepare_profile(profile_id: str) -> None:
    """Resolve the authorized reference and warm CUDA/ONNX state before ready."""
    profile_path = resolve_face_reference(profile_id)
    async with _LOCK:
        await asyncio.to_thread(_initialize, profile_path)


async def transform_face(
    payload: bytes,
    profile_id: str,
    *,
    media_metadata: dict[str, object] | None = None,
) -> bytes:
    """Transform one authorized JPEG frame using the mounted profile reference."""
    metadata = media_metadata or {}
    width = metadata.get("width")
    height = metadata.get("height")
    pixel_format = metadata.get("pixel_format")
    if type(width) is not int or type(height) is not int:
        raise ValueError("face adapter requires frame dimensions")
    if pixel_format not in (None, "jpeg"):
        raise ValueError("FaceFusion live adapter accepts JPEG transport frames")
    async with _LOCK:
        return await asyncio.to_thread(
            _transform_sync,
            payload,
            profile_id,
            width=width,
            height=height,
        )
