import asyncio
import io
import json
import math
from array import array

from PIL import Image

from services.live_media.live_profile_store import (
    load_voice_style,
    resolve_face_reference,
)
from services.live_media.realism_quality_gate import (
    FaceRealismWarmupEvidence,
    RealismQualityPolicy,
    VoiceRealismWarmupEvidence,
    validate_face_warmup,
    validate_voice_warmup,
)
from services.live_media.synthetic_video_labeler import label_jpeg
from services.live_media.voice_style_adapter import transform_voice


def _policy() -> RealismQualityPolicy:
    return RealismQualityPolicy(
        face_min_identity_similarity=0.50,
        face_min_temporal_consistency=0.50,
        face_min_blend_quality=0.40,
        voice_min_speaker_similarity=0.70,
        voice_min_content_preservation=0.70,
        voice_min_naturalness=0.70,
        voice_max_clipped_fraction=0.05,
        voice_max_dropout_fraction=0.05,
        max_processing_p95_ms=250.0,
        max_av_drift_ms=120.0,
    )


def _jpeg(width=1280, height=720) -> bytes:
    image = Image.new("RGB", (width, height), (90, 110, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def test_synthetic_video_labeler_preserves_hd_geometry_and_changes_pixels():
    source = _jpeg()
    labeled = asyncio.run(label_jpeg(source))
    assert labeled != source
    with Image.open(io.BytesIO(labeled)) as image:
        assert image.size == (1280, 720)
        assert image.mode == "RGB"


def test_profile_store_rejects_traversal_and_loads_bounded_voice_style(
    tmp_path, monkeypatch
):
    root = tmp_path / "profiles"
    profile = root / "authorized-1"
    profile.mkdir(parents=True)
    (profile / "face.jpg").write_bytes(_jpeg(256, 256))
    (profile / "voice-style.json").write_text(
        json.dumps({"gain_db": 1.5, "presence": 0.25, "warmth": -0.2}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SELDRUNE_LIVE_PROFILE_ROOT", str(root))

    assert resolve_face_reference("authorized-1").name == "face.jpg"
    style = load_voice_style("authorized-1")
    assert style.gain_db == 1.5
    assert style.presence == 0.25
    assert style.warmth == -0.2

    try:
        resolve_face_reference("../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("profile traversal must be rejected")


def test_voice_style_transform_is_real_time_shape_preserving(tmp_path, monkeypatch):
    root = tmp_path / "profiles"
    profile = root / "voice-1"
    profile.mkdir(parents=True)
    (profile / "voice-style.json").write_text(
        json.dumps({"gain_db": 2.0, "presence": 0.4, "warmth": 0.3}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SELDRUNE_LIVE_PROFILE_ROOT", str(root))

    samples = array(
        "h",
        [
            int(9000 * math.sin(2.0 * math.pi * 220.0 * index / 48000.0))
            for index in range(960)
        ],
    )
    source = samples.tobytes()
    output = asyncio.run(
        transform_voice(
            source,
            "voice-1",
            media_metadata={"sample_rate_hz": 48000, "channels": 1},
        )
    )
    assert len(output) == len(source)
    assert output != source


def test_quality_warmup_is_explicit_instead_of_faking_full_windows():
    policy = _policy()
    face = validate_face_warmup(
        FaceRealismWarmupEvidence(
            evaluator_id="face-eval",
            evaluator_version="1",
            window_frames=12,
            required_window_frames=30,
            output_width=1280,
            output_height=720,
            output_fps=30.0,
        ),
        policy,
    )
    voice = validate_voice_warmup(
        VoiceRealismWarmupEvidence(
            evaluator_id="voice-eval",
            evaluator_version="1",
            window_duration_seconds=0.42,
            required_window_duration_seconds=1.0,
            sample_rate_hz=48000,
            channels=1,
        ),
        policy,
    )
    assert face["state"] == "warming"
    assert face["window_frames"] == 12
    assert voice["state"] == "warming"
    assert voice["window_duration_seconds"] == 0.42
