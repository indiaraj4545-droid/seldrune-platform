from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.services.adaptive_planning import build_adaptive_planning_guidance
from backend.app.services.playbook_engine import consolidate_playbooks
from backend.app.services.playbook_guidance import build_playbook_guidance


def build_learning_guidance(
    session: Session, *, organization_id: UUID, objective: str, actor_user_id: UUID | None = None
) -> tuple[dict, dict]:
    consolidate_playbooks(session, organization_id=organization_id, actor_user_id=actor_user_id)
    adaptive = build_adaptive_planning_guidance(
        session, organization_id=organization_id, objective=objective
    )
    playbook = build_playbook_guidance(
        session, organization_id=organization_id, objective=objective
    )
    return adaptive, playbook
