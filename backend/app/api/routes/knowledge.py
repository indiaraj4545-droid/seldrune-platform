from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.agent import Agent
from backend.app.models.knowledge import KnowledgeEntry
from backend.app.models.membership import Membership
from backend.app.models.memory import MemoryItem
from backend.app.models.task import Task
from backend.app.schemas.knowledge import (
    KnowledgeCreate,
    KnowledgePublic,
    MemoryCreate,
    MemoryPublic,
    RetrievalHit,
    RetrievalResponse,
)
from backend.app.services.audit import record_audit
from backend.app.services.knowledge import search_context

router = APIRouter(prefix="/organizations", tags=["knowledge", "memory"])

knowledge_read_dependency = require_org_permission(Permission.KNOWLEDGE_READ)
knowledge_write_dependency = require_org_permission(Permission.KNOWLEDGE_WRITE)
KnowledgeReadDep = Annotated[Membership, Depends(knowledge_read_dependency)]
KnowledgeWriteDep = Annotated[Membership, Depends(knowledge_write_dependency)]


def _validate_targets(
    session: SessionDep,
    organization_id: UUID,
    agent_id: UUID | None,
    task_id: UUID | None,
) -> None:
    if agent_id is not None:
        agent = session.scalar(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.organization_id == organization_id,
            )
        )
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
    if task_id is not None:
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.organization_id == organization_id,
            )
        )
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")


@router.post(
    "/{organization_id}/knowledge",
    response_model=KnowledgePublic,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge(
    organization_id: UUID,
    payload: KnowledgeCreate,
    _membership: KnowledgeWriteDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> KnowledgeEntry:
    entry = KnowledgeEntry(
        organization_id=organization_id,
        created_by_user_id=current_user.id,
        title=payload.title,
        content=payload.content,
        kind=payload.kind.value,
        tags=sorted(set(tag.strip().lower() for tag in payload.tags if tag.strip())),
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        source_label=payload.source_label,
        metadata_json=payload.metadata,
    )
    session.add(entry)
    session.flush()
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="knowledge.created",
        resource_type="knowledge",
        resource_id=str(entry.id),
        details={"kind": entry.kind, "source_type": entry.source_type},
    )
    session.commit()
    session.refresh(entry)
    return entry


@router.get("/{organization_id}/knowledge", response_model=list[KnowledgePublic])
def list_knowledge(
    organization_id: UUID,
    _membership: KnowledgeReadDep,
    session: SessionDep,
) -> list[KnowledgeEntry]:
    return list(
        session.scalars(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.organization_id == organization_id)
            .order_by(KnowledgeEntry.updated_at.desc())
        )
    )


@router.get("/{organization_id}/knowledge/search", response_model=RetrievalResponse)
def search_knowledge(
    organization_id: UUID,
    _membership: KnowledgeReadDep,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=4000),
    limit: int = Query(default=8, ge=1, le=25),
) -> RetrievalResponse:
    hits = search_context(
        session,
        organization_id=organization_id,
        query=q,
        limit=limit,
    )
    return RetrievalResponse(
        query=q,
        hits=[
            RetrievalHit(
                ref=hit.ref,
                source=hit.source,
                title=hit.title,
                excerpt=hit.excerpt,
                score=hit.score,
                source_uri=hit.source_uri,
            )
            for hit in hits
        ],
    )


@router.post(
    "/{organization_id}/memory",
    response_model=MemoryPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_memory(
    organization_id: UUID,
    payload: MemoryCreate,
    _membership: KnowledgeWriteDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MemoryItem:
    _validate_targets(session, organization_id, payload.agent_id, payload.task_id)
    item = MemoryItem(
        organization_id=organization_id,
        agent_id=payload.agent_id,
        task_id=payload.task_id,
        created_by_user_id=current_user.id,
        scope=payload.scope.value,
        kind=payload.kind.value,
        key=payload.key,
        content=payload.content,
        importance=payload.importance,
        metadata_json=payload.metadata,
        expires_at=payload.expires_at,
    )
    session.add(item)
    session.flush()
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="memory.created",
        resource_type="memory",
        resource_id=str(item.id),
        details={"scope": item.scope, "kind": item.kind},
    )
    session.commit()
    session.refresh(item)
    return item


@router.get("/{organization_id}/memory", response_model=list[MemoryPublic])
def list_memory(
    organization_id: UUID,
    _membership: KnowledgeReadDep,
    session: SessionDep,
) -> list[MemoryItem]:
    return list(
        session.scalars(
            select(MemoryItem)
            .where(MemoryItem.organization_id == organization_id)
            .order_by(MemoryItem.updated_at.desc())
        )
    )
