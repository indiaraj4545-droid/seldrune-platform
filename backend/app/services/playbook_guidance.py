import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.memory import MemoryItem
from backend.app.services.playbook_engine import PLAYBOOK_KIND, PLAYBOOK_VERSION


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def _similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def build_playbook_guidance(
    session: Session, *, organization_id: UUID, objective: str
) -> dict[str, Any]:
    objective_terms = _terms(objective)
    items = list(
        session.scalars(
            select(MemoryItem).where(
                MemoryItem.organization_id == organization_id,
                MemoryItem.kind == PLAYBOOK_KIND,
            )
        )
    )
    matched = []
    for item in items:
        meta = item.metadata_json or {}
        scope = set(meta.get("scope_terms") or [])
        similarity = _similarity(objective_terms, scope) if scope else 0.0
        if meta.get("status") != "active":
            continue
        if scope and similarity < 0.1:
            continue
        if not scope and not meta.get("global_safe"):
            continue
        matched.append(
            {
                "code": meta.get("code"),
                "title": meta.get("title"),
                "evidence_count": int(meta.get("evidence_count") or 0),
                "confidence": float(meta.get("confidence") or 0),
                "action": meta.get("action"),
                "review_on_match": bool(meta.get("review_on_match")),
                "advice": item.content,
            }
        )
    actions = list(dict.fromkeys(x["action"] for x in matched if x["action"]))
    advice = list(dict.fromkeys(x["advice"] for x in matched if x["advice"]))
    return {
        "version": PLAYBOOK_VERSION,
        "applied": bool(matched),
        "playbook_count": len(matched),
        "review_recommended": any(x["review_on_match"] for x in matched),
        "actions": actions[:6],
        "advice": advice[:6],
        "playbooks": matched[:6],
    }
