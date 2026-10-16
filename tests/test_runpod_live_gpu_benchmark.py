from __future__ import annotations

import base64
import os

import pytest

from services.live_media.runpod_live_gpu_benchmark import (
    BenchmarkInputError,
    _decode_environment_payload,
    _profile_face_filename,
    require_synthetic_authorization,
    summarize_latencies,
)


def test_benchmark_requires_explicit_consent_and_synthetic_media() -> None:
    with pytest.raises(BenchmarkInputError):
        require_synthetic_authorization(
            {
                "SELDRUNE_BENCH_CONSENT_CONFIRMED": "true",
                "SELDRUNE_BENCH_SYNTHETIC_MEDIA_INDICATOR_ENABLED": "false",
            }
        )


def test_benchmark_requires_exact_true_consent_values() -> None:
    with pytest.raises(BenchmarkInputError):
        require_synthetic_authorization(
            {
                "SELDRUNE_BENCH_CONSENT_CONFIRMED": "1",
                "SELDRUNE_BENCH_SYNTHETIC_MEDIA_INDICATOR_ENABLED": "true",
            }
        )


def test_latency_summary_measures_sustainable_fps_and_30fps_deadlines() -> None:
    summary = summarize_latencies([20.0, 30.0, 40.0, 50.0], 30.0)

    assert summary == {
        "mean_latency_ms": 35.0,
        "p50_latency_ms": 35.0,
        "p95_latency_ms": 50.0,
        "sustainable_fps": 28.571,
        "frame_deadline_ms": 33.333,
        "deadline_miss_count": 2,
    }


def test_media_payload_is_removed_from_environment_after_bounded_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = base64.b64encode(b"synthetic-payload").decode("ascii")
    monkeypatch.setenv("BENCH_MEDIA", encoded)

    assert _decode_environment_payload("BENCH_MEDIA", 64) == b"synthetic-payload"
    assert "BENCH_MEDIA" not in os.environ


def test_media_payload_rejects_oversize_input_without_disclosing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENCH_MEDIA", base64.b64encode(b"private-bytes").decode("ascii"))

    with pytest.raises(BenchmarkInputError):
        _decode_environment_payload("BENCH_MEDIA", 2)


@pytest.mark.parametrize(
    ("image_header", "expected_filename"),
    [
        (b"\xff\xd8\xff", "face.jpg"),
        (b"\x89PNG\r\n\x1a\n", "face.png"),
        (b"RIFF\x00\x00\x00\x00WEBP", "face.webp"),
    ],
)
def test_profile_reference_extension_matches_encoded_image_format(
    image_header: bytes, expected_filename: str
) -> None:
    assert _profile_face_filename(image_header) == expected_filename
