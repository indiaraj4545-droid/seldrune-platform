from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.knowledge import MemoryScope
from backend.app.models.knowledge import KnowledgeEntry
from backend.app.models.memory import MemoryItem
from backend.app.models.task import Task

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]+")


@dataclass(frozen=True)
class RetrievalRecord:
    ref: str
    source: str
    title: str
    excerpt: str
    score: int
    source_uri: str | None = None


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _excerpt(text: str, limit: int = 700) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _score(
    query: str,
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
    importance: int = 50,
) -> int:
    query_terms = _tokens(query)
    if not query_terms:
        return 0
    title_terms = _tokens(title)
    content_terms = _tokens(content)
    tag_terms = _tokens(" ".join(tags or []))
    score = 0
    score += len(query_terms & title_terms) * 5
    score += len(query_terms & tag_terms) * 4
    score += len(query_terms & content_terms) * 2
    normalized = " ".join(query.lower().split())
    if normalized and normalized in title.lower():
        score += 8
    if normalized and normalized in content.lower():
        score += 5
    score += max(0, min(importance, 100)) // 25
    return score


def search_context(
    session: Session,
    *,
    organization_id: UUID,
    query: str,
    agent_id: UUID | None = None,
    task_id: UUID | None = None,
    limit: int = 8,
) -> list[RetrievalRecord]:
    knowledge = list(
        session.scalars(
            select(KnowledgeEntry).where(KnowledgeEntry.organization_id == organization_id)
        )
    )
    now = datetime.now(UTC)
    memory_filters = [MemoryItem.organization_id == organization_id]
    scope_filters = [MemoryItem.scope == MemoryScope.ORGANIZATION.value]
    if agent_id is not None:
        scope_filters.append(MemoryItem.agent_id == agent_id)
    if task_id is not None:
        scope_filters.append(MemoryItem.task_id == task_id)
    memory_filters.append(or_(*scope_filters))
    memories = list(session.scalars(select(MemoryItem).where(*memory_filters)))

    ranked: list[RetrievalRecord] = []
    for entry in knowledge:
        score = _score(query, title=entry.title, content=entry.content, tags=entry.tags)
        if score <= 0:
            continue
        ranked.append(
            RetrievalRecord(
                ref=f"knowledge:{entry.id}",
                source="knowledge",
                title=entry.title,
                excerpt=_excerpt(entry.content),
                score=score,
                source_uri=entry.source_uri,
            )
        )

    for item in memories:
        if item.expires_at is not None:
            expires = item.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= now:
                continue
        score = _score(
            query,
            title=item.key,
            content=item.content,
            importance=item.importance,
        )
        if score <= 0:
            continue
        ranked.append(
            RetrievalRecord(
                ref=f"memory:{item.id}",
                source="memory",
                title=item.key,
                excerpt=_excerpt(item.content),
                score=score,
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.ref))
    return ranked[: max(1, min(limit, 25))]


def task_retrieval_query(task: Task) -> str:
    payload = json.dumps(task.input_data or {}, sort_keys=True, default=str)
    return f"{task.title} {task.objective} {payload}"[:12_000]


def build_agent_context(
    session: Session,
    *,
    task: Task,
    agent_id: UUID,
    limit: int = 6,
    max_chars: int = 6000,
) -> tuple[str, list[str]]:
    hits = search_context(
        session,
        organization_id=task.organization_id,
        query=task_retrieval_query(task),
        agent_id=agent_id,
        task_id=task.id,
        limit=limit,
    )
    if not hits:
        return "", []

    lines = ["Relevant Seldrune internal context:"]
    refs: list[str] = []
    used = len(lines[0])
    for hit in hits:
        line = f"[{hit.ref}] {hit.title}: {hit.excerpt}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        refs.append(hit.ref)
        used += len(line)
    lines.append(
        "Use this context only when relevant and preserve the references in your reasoning."
    )
    return "\n".join(lines), refs


def remember_task_result(
    session: Session,
    *,
    task: Task,
    agent_id: UUID,
    created_by_user_id: UUID,
    result_text: str,
    context_refs: list[str],
) -> MemoryItem:
    memory = MemoryItem(
        organization_id=task.organization_id,
        agent_id=agent_id,
        task_id=task.id,
        created_by_user_id=created_by_user_id,
        scope=MemoryScope.TASK.value,
        kind="result",
        key=f"Result: {task.title}"[:240],
        content=result_text[:50_000],
        importance=70,
        metadata_json={"context_refs": context_refs},
    )
    session.add(memory)
    return memory
