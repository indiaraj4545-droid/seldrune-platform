from __future__ import annotations

import hashlib

import pytest

from backend.app.services.unarchi_engine import UnarchiEngine
from backend.app.services.unarchi_multimodal import (
    ingest_multimodal_observation,
    normalize_multimodal_observation,
)


@pytest.mark.parametrize(
    ("modality", "media_type"),
    (
        ("image", "image/png"),
        ("audio", "audio/wav"),
        ("video", "video/mp4"),
        ("document", "application/pdf"),
        ("structured_data", "application/json"),
    ),
)
def test_v038_normalizes_supported_modalities_with_explicit_lineage(
    modality: str,
    media_type: str,
) -> None:
    payload = f"{modality}-payload".encode()
    evidence = normalize_multimodal_observation(
        modality=modality,
        media_type=media_type,
        source_name=f"sample-{modality}",
        source_bytes=payload,
        summary=f"Verified summary for {modality}.",
        confidence=0.85,
        verification_reason="verified_multimodal_observation",
        source_refs=(f"verification:{modality}",),
        transformation_lineage=("extract:v1", "verify:v1"),
    )

    assert evidence.modality == modality
    assert evidence.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert evidence.transformation_lineage == ("extract:v1", "verify:v1")
    assert f"modality:{modality}" in evidence.source_refs
    assert f"sha256:{evidence.source_sha256}" in evidence.source_refs
    assert f"multimodal-evidence:{evidence.evidence_key}" in evidence.source_refs


def test_v038_ingestion_is_idempotent_and_survives_restart() -> None:
    engine = UnarchiEngine()
    evidence = normalize_multimodal_observation(
        modality="structured_data",
        media_type="application/json",
        source_name="telemetry.json",
        source_bytes=b'{"temperature":88,"limit":70}',
        summary="Temperature is 88 while the configured limit is 70.",
        confidence=0.94,
        verification_reason="verified_multimodal_observation",
        source_refs=("verification:telemetry:1",),
        transformation_lineage=("json-parse:v1", "schema-validate:v1"),
    )

    first = ingest_multimodal_observation(
        engine,
        evidence,
        goal="understand verified telemetry",
    )
    history_size = len(engine.observation_history)
    replay = ingest_multimodal_observation(
        engine,
        evidence,
        goal="understand verified telemetry",
    )

    assert replay.id == first.id
    assert len(engine.observation_history) == history_size
    assert first.kind == "multimodal:structured_data"

    restored = UnarchiEngine.from_export(engine.export_state())
    hits = restored.retrieve_persistent_memory(
        "temperature configured limit telemetry"
    )

    assert restored.snapshot()["version"] == "unarchi-v0.40"
    assert len(restored.observation_history) == history_size
    assert hits
    assert hits[0].record_id == first.id
    assert hits[0].kind == "multimodal:structured_data"


def test_v038_multimodal_normalization_fails_closed() -> None:
    kwargs = {
        "modality": "image",
        "media_type": "image/png",
        "source_name": "panel.png",
        "source_bytes": b"panel",
        "summary": "Verified panel state.",
        "confidence": 0.9,
        "source_refs": ("verification:panel:1",),
        "transformation_lineage": ("vision-caption:v1",),
    }

    with pytest.raises(ValueError, match="not verified"):
        normalize_multimodal_observation(
            **kwargs,
            verification_reason="model_claim_only",
        )

    with pytest.raises(ValueError, match="media type"):
        normalize_multimodal_observation(
            **{**kwargs, "media_type": "audio/wav"},
            verification_reason="verified_multimodal_observation",
        )

    with pytest.raises(ValueError, match="does not match"):
        normalize_multimodal_observation(
            **kwargs,
            source_sha256="0" * 64,
            verification_reason="verified_multimodal_observation",
        )
