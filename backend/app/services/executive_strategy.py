from __future__ import annotations

from collections import Counter
from typing import Any


def _strategy_mode(priority: dict[str, Any]) -> str:
    action = priority.get("action") or {}
    if action.get("kind") != "owner_command":
        return "observe"

    escalation = priority.get("escalation") or {}
    if int(escalation.get("level") or 0) > 0:
        return "recover"

    memory = priority.get("outcome_memory") or {}
    has_preferred = bool(memory.get("preferred_pattern"))
    has_avoid = bool(memory.get("avoid_patterns"))
    if has_preferred and has_avoid:
        return "adapt"
    if has_preferred:
        return "reuse"
    if has_avoid:
        return "explore"
    return "baseline"


def _required_evidence(mode: str) -> list[str]:
    if mode == "observe":
        return ["Continue monitoring the source evidence until owner action is warranted."]
    if mode == "recover":
        return [
            "Explain why the previous governed attempt did not clear the priority.",
            "Use a materially different recovery approach.",
            "Define explicit completion evidence before execution.",
        ]
    if mode == "reuse":
        return [
            "State which prior resolution-associated pattern is being adapted.",
            "Verify that current conditions are sufficiently similar before reuse.",
            "Define the evidence that will confirm the priority actually cleared.",
        ]
    if mode == "adapt":
        return [
            "Preserve the useful parts of prior resolution-associated evidence.",
            "Explicitly avoid unsuccessful patterns unless new evidence justifies them.",
            "Define the evidence that distinguishes improvement from recurrence.",
        ]
    if mode == "explore":
        return [
            "Do not repeat unsuccessful prior patterns without new evidence.",
            "Choose a materially different first-principles approach.",
            "Define falsifiable completion evidence before execution.",
        ]
    return [
        "Use first-principles reasoning because no comparable outcome evidence exists yet.",
        "Define explicit completion evidence before execution.",
    ]


def _rationale(mode: str) -> str:
    return {
        "observe": (
            "The priority is informational or navigational, so no governed command is required."
        ),
        "recover": (
            "The priority persisted after completed governed action, so the next command must be a "
            "materially different recovery strategy."
        ),
        "reuse": (
            "A comparable resolution-associated pattern exists and may be adapted with explicit "
            "verification rather than copied blindly."
        ),
        "adapt": (
            "Both resolution-associated and unsuccessful patterns exist, so the next command "
            "should combine useful evidence while avoiding known failure modes."
        ),
        "explore": (
            "Comparable unsuccessful attempts exist without a resolution-associated pattern, so a "
            "different strategy is required."
        ),
        "baseline": (
            "No comparable outcome evidence exists yet, so the first governed response should be "
            "built from current evidence and explicit verification criteria."
        ),
    }[mode]


def _outcome_score(priority: dict[str, Any], mode: str) -> dict[str, Any]:
    outcomes = priority.get("strategy_outcomes") or {}
    modes = outcomes.get("modes") or {}
    score = modes.get(mode) or {}
    return {
        "family": outcomes.get("family"),
        "family_attempts": outcomes.get("total_attempts", 0),
        "attempts": score.get("attempts", 0),
        "resolution_associations": score.get("resolution_associations", 0),
        "persisted_after_success": score.get("persisted_after_success", 0),
        "unsuccessful_attempts": score.get("unsuccessful_attempts", 0),
        "resolution_rate": score.get("resolution_rate", 0.0),
        "evidence_strength": score.get("evidence_strength", "none"),
        "causal_claim": False,
    }


def _strategy(priority: dict[str, Any]) -> dict[str, Any]:
    mode = _strategy_mode(priority)
    memory = priority.get("outcome_memory") or {}
    preferred = memory.get("preferred_pattern") or {}
    avoid = memory.get("avoid_patterns") or []
    preferred_id = preferred.get("command_id")
    avoid_ids = [item.get("command_id") for item in avoid[:3] if item.get("command_id")]
    outcome_score = _outcome_score(priority, mode)
    history_informed = bool(
        preferred_id
        or avoid_ids
        or mode == "recover"
        or outcome_score["family_attempts"]
    )
    return {
        "mode": mode,
        "rationale": _rationale(mode),
        "confidence": memory.get("confidence", "none"),
        "history_informed": history_informed,
        "preferred_reference_command_id": preferred_id,
        "avoid_reference_command_ids": avoid_ids,
        "required_evidence": _required_evidence(mode),
        "outcome_score": outcome_score,
        "owner_approval_required": (priority.get("action") or {}).get("kind") == "owner_command",
        "causal_claim": False,
    }


def evaluate_executive_strategies(priorities: list[dict[str, Any]]) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    modes: Counter[str] = Counter()
    history_informed = 0
    actionable = 0

    for priority in priorities:
        strategy = _strategy(priority)
        enriched.append({**priority, "strategy": strategy})
        modes[strategy["mode"]] += 1
        if strategy["history_informed"]:
            history_informed += 1
        if strategy["owner_approval_required"]:
            actionable += 1

    return {
        "priorities": enriched,
        "summary": {
            "actionable_priorities": actionable,
            "history_informed_priorities": history_informed,
            "modes": dict(sorted(modes.items())),
        },
    }
