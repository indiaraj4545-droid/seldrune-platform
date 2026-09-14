from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.memory import MemoryItem
from backend.app.services.playbook_rules import RULES, scope_terms
from backend.app.services.reflection_engine import REFLECTION_KIND

PLAYBOOK_KIND = "operational_playbook"
PLAYBOOK_VERSION = "playbook-v1"
MIN_EVIDENCE = 2


def _signals(item: MemoryItem) -> set[str]:
    reflection = ((item.metadata_json or {}).get("reflection") or {})
    return set(reflection.get("recommendations") or []) | set(reflection.get("cautions") or [])


def consolidate_playbooks(
    session: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None = None,
) -> list[MemoryItem]:
    reflections = list(
        session.scalars(
            select(MemoryItem).where(
                MemoryItem.organization_id == organization_id,
                MemoryItem.kind == REFLECTION_KIND,
            )
        )
    )
    active: list[MemoryItem] = []
    changed = False
    for code, rule in RULES.items():
        supporting = [item for item in reflections if _signals(item) & rule["signals"]]
        if len(supporting) < MIN_EVIDENCE:
            continue
        metadata = {
            "version": PLAYBOOK_VERSION,
            "code": code,
            "title": rule["title"],
            "status": "active",
            "evidence_count": len(supporting),
            "confidence": round(min(1.0, len(supporting) / 4), 3),
            "scope_terms": scope_terms(supporting),
            "action": rule["action"],
            "review_on_match": rule["review"],
            "global_safe": rule["global_safe"],
        }
        item = session.scalar(
            select(MemoryItem).where(
                MemoryItem.organization_id == organization_id,
                MemoryItem.kind == PLAYBOOK_KIND,
                MemoryItem.key == f"playbook:{code}",
            )
        )
        if item is None:
            item = MemoryItem(
                organization_id=organization_id,
                created_by_user_id=actor_user_id,
                scope="organization",
                kind=PLAYBOOK_KIND,
                key=f"playbook:{code}",
                content=rule["advice"],
                importance=90,
                metadata_json=metadata,
            )
            session.add(item)
            changed = True
        elif item.metadata_json != metadata:
            item.metadata_json = metadata
            changed = True
        active.append(item)
    if changed:
        session.commit()
    return active
