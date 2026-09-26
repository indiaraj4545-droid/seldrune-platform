from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


CandidateKind = Literal["model", "tool"]


@dataclass(frozen=True)
class CognitiveRouteCandidate:
    kind: CandidateKind
    identifier: str
    capabilities: tuple[str, ...]
    estimated_cost_usd: float
    confidence: float
    recent_verified_success_rate: float | None = None
    recent_verified_samples: int = 0
    lifetime_verified_success_rate: float | None = None
    evidence_refs: tuple[str, ...] = ()
    allowed: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CognitiveRouteDecision:
    selected_kind: CandidateKind
    selected_identifier: str
    required_capabilities: tuple[str, ...]
    score: float
    capability_score: float
    confidence_score: float
    outcome_score: float
    cost_score: float
    evidence_refs: tuple[str, ...]
    considered: tuple[tuple[str, float], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalized_capabilities(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value.strip().lower().replace("-", "_")
            for value in values
            if value.strip()
        )
    )


def select_cognitive_route(
    *,
    candidates: tuple[CognitiveRouteCandidate, ...],
    required_capabilities: tuple[str, ...],
    max_cost_usd: float,
    minimum_confidence: float = 0.50,
    minimum_recent_samples: int = 2,
) -> CognitiveRouteDecision:
    """
    Deterministically select a model or governed tool route.

    Selection is advisory only. It does not execute a model or tool. Candidates
    must satisfy required capabilities, explicit cost bounds, confidence floors,
    and provenance requirements for any claimed outcome-derived trust.
    """
    if max_cost_usd < 0:
        raise ValueError("max_cost_usd cannot be negative")
    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("minimum_confidence must be within 0..1")
    if minimum_recent_samples < 1:
        raise ValueError("minimum_recent_samples must be positive")

    required = _normalized_capabilities(required_capabilities)
    if not required:
        raise ValueError("at least one required capability is required")

    ranked: list[
        tuple[
            float,
            CognitiveRouteCandidate,
            tuple[str, ...],
            tuple[float, ...],
        ]
    ] = []
    for candidate in candidates:
        identifier = candidate.identifier.strip()
        if not candidate.allowed or not identifier:
            continue
        if (
            candidate.estimated_cost_usd < 0
            or candidate.estimated_cost_usd > max_cost_usd
        ):
            continue
        if not 0.0 <= candidate.confidence <= 1.0:
            raise ValueError("candidate confidence must be within 0..1")
        if candidate.confidence < minimum_confidence:
            continue

        available = set(_normalized_capabilities(candidate.capabilities))
        if not set(required).issubset(available):
            continue
        capability_score = 1.0

        recent = candidate.recent_verified_success_rate
        lifetime = candidate.lifetime_verified_success_rate
        outcome_score = 0.5
        refs = tuple(
            dict.fromkeys(
                ref for ref in candidate.evidence_refs if ref.strip()
            )
        )

        if recent is not None or lifetime is not None:
            if not refs:
                raise ValueError(
                    "outcome-derived cognitive routing requires "
                    "provenance evidence"
                )
            if recent is not None and not 0.0 <= recent <= 1.0:
                raise ValueError("recent success rate must be within 0..1")
            if lifetime is not None and not 0.0 <= lifetime <= 1.0:
                raise ValueError("lifetime success rate must be within 0..1")

            if (
                recent is not None
                and candidate.recent_verified_samples >= minimum_recent_samples
            ):
                outcome_score = (
                    0.80 * recent
                    + 0.20 * (lifetime if lifetime is not None else recent)
                )
            elif lifetime is not None:
                outcome_score = lifetime

        confidence_score = candidate.confidence
        if max_cost_usd == 0:
            cost_score = 1.0 if candidate.estimated_cost_usd == 0 else 0.0
        else:
            cost_score = max(
                0.0,
                1.0 - (candidate.estimated_cost_usd / max_cost_usd),
            )

        score = (
            capability_score * 0.35
            + confidence_score * 0.25
            + outcome_score * 0.25
            + cost_score * 0.15
        )
        ranked.append(
            (
                round(score, 6),
                candidate,
                refs,
                (
                    capability_score,
                    confidence_score,
                    outcome_score,
                    cost_score,
                ),
            )
        )

    if not ranked:
        raise ValueError(
            "no eligible model or tool route satisfies capability, cost, "
            "confidence, and provenance constraints"
        )

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].estimated_cost_usd,
            item[1].kind,
            item[1].identifier,
        )
    )
    score, selected, refs, components = ranked[0]
    return CognitiveRouteDecision(
        selected_kind=selected.kind,
        selected_identifier=selected.identifier,
        required_capabilities=required,
        score=score,
        capability_score=round(components[0], 6),
        confidence_score=round(components[1], 6),
        outcome_score=round(components[2], 6),
        cost_score=round(components[3], 6),
        evidence_refs=refs,
        considered=tuple(
            (candidate.identifier, candidate_score)
            for candidate_score, candidate, _refs, _components in ranked
        ),
    )
