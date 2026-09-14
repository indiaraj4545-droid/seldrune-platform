from __future__ import annotations

import math
from collections import Counter
from typing import Any

from backend.app.models.memory import MemoryItem

RULES: dict[str, dict[str, Any]] = {
    "narrow_steps": {
        "title": "Prefer narrow capability-specific steps",
        "signals": {
            "prefer_high_fit_agent_routes_for_similar_capabilities",
            "raise_routing_quality_before_similar_execution",
            "low_agent_fit_was_present",
        },
        "advice": "Keep each plan step focused on one primary capability for high-fit routing.",
        "action": "prefer_single_capability_steps",
        "review": False,
        "global_safe": True,
    },
    "preserve_research": {
        "title": "Preserve useful evidence gathering",
        "signals": {"preserve_research_preflight_for_similar_work"},
        "advice": "Preserve research when similar work historically benefited from it.",
        "action": "ensure_research_step",
        "review": False,
        "global_safe": False,
    },
    "validate_weak_patterns": {
        "title": "Validate repeatedly weak execution patterns",
        "signals": {
            "review_failed_capabilities_before_repeating_similar_work",
            "require_review_before_retry",
            "task_failures_were_observed",
            "orchestration_did_not_complete_cleanly",
        },
        "advice": "Add validation for work resembling repeated weak outcomes.",
        "action": "ensure_validation_step",
        "review": True,
        "global_safe": False,
    },
    "readiness_checks": {
        "title": "Check readiness before historically blocked work",
        "signals": {
            "resolve_assignment_or_dependency_blockers_before_retry",
            "execution_encountered_blocked_steps",
        },
        "advice": "Expose dependencies and readiness checks before historically blocked work.",
        "action": "require_readiness_checks",
        "review": True,
        "global_safe": False,
    },
}


def scope_terms(items: list[MemoryItem]) -> list[str]:
    counts: Counter[str] = Counter()
    for item in items:
        counts.update(set((item.metadata_json or {}).get("objective_terms") or []))
    threshold = max(2, math.ceil(len(items) * 0.5))
    ranked = sorted(
        ((term, count) for term, count in counts.items() if count >= threshold),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return [term for term, _ in ranked[:10]]
