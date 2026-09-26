from __future__ import annotations

import pytest

from backend.app.services.unarchi_orchestration import (
    CognitiveRouteCandidate,
    select_cognitive_route,
)


def test_v039_prefers_lower_cost_high_trust_model_when_capabilities_match() -> None:
    decision = select_cognitive_route(
        candidates=(
            CognitiveRouteCandidate(
                kind="model",
                identifier="expensive",
                capabilities=("text", "reasoning"),
                estimated_cost_usd=0.15,
                confidence=0.95,
                recent_verified_success_rate=0.94,
                recent_verified_samples=5,
                lifetime_verified_success_rate=0.92,
                evidence_refs=("receipt:expensive",),
            ),
            CognitiveRouteCandidate(
                kind="model",
                identifier="efficient",
                capabilities=("text", "reasoning"),
                estimated_cost_usd=0.02,
                confidence=0.90,
                recent_verified_success_rate=0.93,
                recent_verified_samples=5,
                lifetime_verified_success_rate=0.89,
                evidence_refs=("receipt:efficient",),
            ),
        ),
        required_capabilities=("text", "reasoning"),
        max_cost_usd=0.20,
    )

    assert decision.selected_identifier == "efficient"
    assert decision.selected_kind == "model"
    assert decision.evidence_refs == ("receipt:efficient",)


def test_v039_can_select_governed_tool_over_model_for_matching_skill() -> None:
    decision = select_cognitive_route(
        candidates=(
            CognitiveRouteCandidate(
                kind="model",
                identifier="general-model",
                capabilities=("text", "structured_output"),
                estimated_cost_usd=0.03,
                confidence=0.90,
                recent_verified_success_rate=0.90,
                recent_verified_samples=4,
                evidence_refs=("receipt:model",),
            ),
            CognitiveRouteCandidate(
                kind="tool",
                identifier="internal-json-validate",
                capabilities=("structured_output", "validation"),
                estimated_cost_usd=0.0,
                confidence=0.99,
                recent_verified_success_rate=1.0,
                recent_verified_samples=10,
                evidence_refs=("tool-run:1", "receipt:tool:1"),
            ),
        ),
        required_capabilities=("structured_output", "validation"),
        max_cost_usd=0.05,
    )

    assert decision.selected_kind == "tool"
    assert decision.selected_identifier == "internal-json-validate"
    assert decision.cost_score == 1.0


def test_v039_fails_closed_for_unproven_outcomes_and_budget_miss() -> None:
    with pytest.raises(ValueError, match="provenance"):
        select_cognitive_route(
            candidates=(
                CognitiveRouteCandidate(
                    kind="model",
                    identifier="unverified",
                    capabilities=("text", "reasoning"),
                    estimated_cost_usd=0.0,
                    confidence=0.95,
                    recent_verified_success_rate=1.0,
                    recent_verified_samples=5,
                    evidence_refs=(),
                ),
            ),
            required_capabilities=("text", "reasoning"),
            max_cost_usd=0.10,
        )

    with pytest.raises(ValueError, match="no eligible"):
        select_cognitive_route(
            candidates=(
                CognitiveRouteCandidate(
                    kind="model",
                    identifier="over-budget",
                    capabilities=("text", "reasoning"),
                    estimated_cost_usd=0.50,
                    confidence=0.95,
                ),
            ),
            required_capabilities=("text", "reasoning"),
            max_cost_usd=0.10,
        )
