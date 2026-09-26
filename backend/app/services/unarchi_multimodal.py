from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re

from backend.app.services.unarchi_engine import (
    PersistentMemoryRecord,
    UnarchiEngine,
)


SUPPORTED_MODALITIES = {
    "image",
    "audio",
    "video",
    "document",
    "structured_data",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MultimodalEvidence:
    modality: str
    media_type: str
    source_name: str
    source_sha256: str
    summary: str
    confidence: float
    transformation_lineage: tuple[str, ...]
    source_refs: tuple[str, ...]
    evidence_key: str
    normalized_text: str
    verification_reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _media_type_matches(modality: str, media_type: str) -> bool:
    if modality == "image":
        return media_type.startswith("image/")
    if modality == "audio":
        return media_type.startswith("audio/")
    if modality == "video":
        return media_type.startswith("video/")
    if modality == "document":
        return (
            media_type in {
                "application/pdf",
                "text/plain",
                "text/markdown",
                "application/msword",
                (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                (
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
            }
            or media_type.startswith("text/")
            and media_type not in {"text/csv"}
        )
    if modality == "structured_data":
        return media_type in {
            "application/json",
            "application/ld+json",
            "application/xml",
            "text/csv",
            "application/csv",
            "text/tab-separated-values",
            (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        }
    return False


def normalize_multimodal_observation(
    *,
    modality: str,
    media_type: str,
    source_name: str,
    summary: str,
    confidence: float,
    verification_reason: str,
    source_refs: tuple[str, ...],
    transformation_lineage: tuple[str, ...],
    source_bytes: bytes | None = None,
    source_sha256: str | None = None,
) -> MultimodalEvidence:
    """
    Normalize one already-verified multimodal observation into evidence.

    The function does not call models, tools, or external services. It requires
    explicit provenance, source identity, confidence, and transformation
    lineage before evidence can enter the UNARCHI memory path.
    """
    clean_modality = modality.strip().lower().replace("-", "_")
    clean_media_type = media_type.strip().lower()
    clean_name = source_name.strip()
    clean_summary = summary.strip()
    clean_reason = verification_reason.strip()

    if clean_modality not in SUPPORTED_MODALITIES:
        raise ValueError("unsupported multimodal observation modality")
    if clean_reason != "verified_multimodal_observation":
        raise ValueError("multimodal observation is not verified")
    if not clean_media_type or not _media_type_matches(
        clean_modality,
        clean_media_type,
    ):
        raise ValueError("media type does not match multimodal observation")
    if not clean_name:
        raise ValueError("multimodal observation source_name is required")
    if not clean_summary:
        raise ValueError("multimodal observation summary is required")

    bounded_confidence = float(confidence)
    if not 0.0 <= bounded_confidence <= 1.0:
        raise ValueError("multimodal observation confidence must be within 0..1")

    refs = tuple(
        dict.fromkeys(
            str(ref).strip()[:300]
            for ref in source_refs
            if str(ref).strip()
        )
    )
    if not refs:
        raise ValueError("multimodal observation requires provenance source_refs")

    lineage = tuple(
        dict.fromkeys(
            str(step).strip()[:200]
            for step in transformation_lineage
            if str(step).strip()
        )
    )
    if not lineage:
        raise ValueError("multimodal observation requires transformation lineage")
    if len(lineage) > 12:
        raise ValueError("multimodal observation lineage exceeds bounded depth")

    computed_digest = (
        hashlib.sha256(source_bytes).hexdigest()
        if source_bytes is not None
        else None
    )
    supplied_digest = (source_sha256 or "").strip().lower() or None
    if supplied_digest is not None and not _SHA256_RE.fullmatch(supplied_digest):
        raise ValueError("invalid multimodal source sha256")
    if computed_digest is None and supplied_digest is None:
        raise ValueError("multimodal observation requires source bytes or sha256")
    if (
        computed_digest is not None
        and supplied_digest is not None
        and computed_digest != supplied_digest
    ):
        raise ValueError("multimodal source sha256 does not match source bytes")
    digest = computed_digest or supplied_digest
    if digest is None:
        raise ValueError("multimodal source digest is unavailable")

    key_material = "\x1f".join(
        (
            clean_modality,
            clean_media_type,
            clean_name,
            digest,
            clean_summary,
            f"{bounded_confidence:.6f}",
            *lineage,
        )
    )
    evidence_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    canonical_refs = tuple(
        dict.fromkeys(
            (
                *refs,
                f"modality:{clean_modality}",
                f"media-type:{clean_media_type}",
                f"sha256:{digest}",
                *(f"transform:{step}" for step in lineage),
                f"multimodal-evidence:{evidence_key}",
            )
        )
    )
    normalized_text = (
        f"Verified {clean_modality} observation from {clean_name} "
        f"({clean_media_type}, sha256={digest}, "
        f"confidence={bounded_confidence:.3f}). "
        f"Summary: {clean_summary} "
        f"Transformation lineage: {' -> '.join(lineage)}."
    )

    return MultimodalEvidence(
        modality=clean_modality,
        media_type=clean_media_type,
        source_name=clean_name[:240],
        source_sha256=digest,
        summary=clean_summary[:4000],
        confidence=round(bounded_confidence, 6),
        transformation_lineage=lineage,
        source_refs=canonical_refs,
        evidence_key=evidence_key,
        normalized_text=normalized_text[:6000],
        verification_reason=clean_reason,
    )


def ingest_multimodal_observation(
    engine: UnarchiEngine,
    evidence: MultimodalEvidence,
    *,
    goal: str,
) -> PersistentMemoryRecord:
    """
    Feed normalized evidence into the bounded observation and durable-memory path.

    Replaying the same evidence key is idempotent and does not cause a second
    observation cycle.
    """
    clean_goal = goal.strip()
    if not clean_goal:
        raise ValueError("multimodal observation goal is required")

    key_ref = f"multimodal-evidence:{evidence.evidence_key}"
    existing = next(
        (
            item
            for item in engine.persistent_memory
            if key_ref in item.source_refs
        ),
        None,
    )
    if existing is not None:
        return existing

    engine.cycle(
        observation=evidence.normalized_text,
        goal=clean_goal[:1000],
        expected_success=evidence.confidence,
        risk=1.0 - evidence.confidence,
        generate_internal_goal=False,
    )
    return engine.remember_persistent_memory(
        content=evidence.normalized_text,
        source_refs=evidence.source_refs,
        kind=f"multimodal:{evidence.modality}",
        confidence=evidence.confidence,
        importance=max(0.55, evidence.confidence),
    )
