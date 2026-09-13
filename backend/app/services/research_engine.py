from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.knowledge import KnowledgeKind
from backend.app.core.research import ConnectorStatus, ResearchSourceStatus, ResearchStatus
from backend.app.models.knowledge import KnowledgeEntry
from backend.app.models.research_connector import ResearchConnector
from backend.app.models.research_session import ResearchSession
from backend.app.models.research_source import ResearchSource
from backend.app.models.secret_reference import SecretReference
from backend.app.services.audit import record_audit
from backend.app.services.secret_vault import SecretVaultError, resolve_secret


class ResearchEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchDocument:
    title: str
    content: str
    uri: str | None = None
    source_type: str = "external"
    metadata: dict[str, Any] | None = None


class HttpTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        max_bytes: int,
    ) -> tuple[int, str, str]: ...


class UrllibHttpTransport:
    @staticmethod
    def _validate_public_host(host: str) -> None:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ResearchEngineError("Connector host could not be resolved") from exc
        for address in addresses:
            value = ipaddress.ip_address(address[4][0])
            if not value.is_global:
                raise ResearchEngineError("Connector host resolves to a non-public address")

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        max_bytes: int,
    ) -> tuple[int, str, str]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ResearchEngineError("Live connectors require HTTPS URLs")
        self._validate_public_host(parsed.hostname)
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise ResearchEngineError("External source exceeded the configured size limit")
                charset = response.headers.get_content_charset() or "utf-8"
                content_type = response.headers.get_content_type() or "text/plain"
                return response.status, content_type, payload.decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ResearchEngineError(f"External source request failed: {exc}") from exc


class ResearchAdapter(Protocol):
    def fetch(
        self,
        *,
        query: str,
        config: dict[str, Any],
        limit: int,
        credential: str | None = None,
    ) -> list[ResearchDocument]: ...


class FixtureResearchAdapter:
    def fetch(
        self,
        *,
        query: str,
        config: dict[str, Any],
        limit: int,
        credential: str | None = None,
    ) -> list[ResearchDocument]:
        del credential
        raw_documents = config.get("documents", [])
        if not isinstance(raw_documents, list):
            raise ResearchEngineError("Fixture connector documents must be a list")
        terms = {term.lower() for term in query.split() if len(term) > 1}
        results: list[ResearchDocument] = []
        for raw in raw_documents:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            content = str(raw.get("content", "")).strip()
            if not title or not content:
                continue
            if terms and not any(term in f"{title} {content}".lower() for term in terms):
                continue
            metadata = raw.get("metadata")
            results.append(
                ResearchDocument(
                    title=title,
                    content=content,
                    uri=str(raw["uri"]) if raw.get("uri") else None,
                    source_type=str(raw.get("source_type", "fixture")),
                    metadata=metadata if isinstance(metadata, dict) else {},
                )
            )
            if len(results) >= limit:
                break
        return results


class PublicWebResearchAdapter:
    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or UrllibHttpTransport()

    def fetch(
        self,
        *,
        query: str,
        config: dict[str, Any],
        limit: int,
        credential: str | None = None,
    ) -> list[ResearchDocument]:
        del query, credential
        urls = config.get("urls", [])
        allowed_hosts = {str(value).lower() for value in config.get("_allowed_hosts", [])}
        budget = min(limit, int(config.get("_max_requests", limit)))
        if not isinstance(urls, list) or not allowed_hosts:
            raise ResearchEngineError("Web connector requires URLs and an explicit host allow-list")
        results: list[ResearchDocument] = []
        for raw_url in urls[:budget]:
            url = str(raw_url).strip()
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or host not in allowed_hosts:
                raise ResearchEngineError("Web connector URL is outside the approved host allow-list")
            status, content_type, text = self.transport.get(
                url,
                headers={"User-Agent": "SeldruneResearch/0.11"},
                timeout=15.0,
                max_bytes=1_000_000,
            )
            if status != 200:
                continue
            results.append(
                ResearchDocument(
                    title=host + parsed.path,
                    content=text,
                    uri=url,
                    source_type="web",
                    metadata={"content_type": content_type, "http_status": status},
                )
            )
        return results


class GitHubResearchAdapter:
    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or UrllibHttpTransport()

    def fetch(
        self,
        *,
        query: str,
        config: dict[str, Any],
        limit: int,
        credential: str | None = None,
    ) -> list[ResearchDocument]:
        del query
        requested = [str(value).strip() for value in config.get("repositories", [])]
        allowed = {str(value).strip().lower() for value in config.get("_allowed_repositories", [])}
        budget = min(limit, int(config.get("_max_requests", limit)))
        if not requested or not allowed:
            raise ResearchEngineError("GitHub connector requires an explicit repository allow-list")
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "SeldruneResearch/0.11",
        }
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        results: list[ResearchDocument] = []
        for repository in requested[:budget]:
            if repository.lower() not in allowed or repository.count("/") != 1:
                raise ResearchEngineError("GitHub repository is outside the approved allow-list")
            url = f"https://api.github.com/repos/{repository}/readme"
            status, content_type, text = self.transport.get(
                url,
                headers=headers,
                timeout=15.0,
                max_bytes=1_000_000,
            )
            if status != 200:
                continue
            results.append(
                ResearchDocument(
                    title=f"{repository} README",
                    content=text,
                    uri=f"https://github.com/{repository}",
                    source_type="github",
                    metadata={"repository": repository, "content_type": content_type},
                )
            )
        return results


class ResearchConnectorRegistry:
    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._adapters: dict[str, ResearchAdapter] = {
            "fixture": FixtureResearchAdapter(),
            "web": PublicWebResearchAdapter(transport),
            "github": GitHubResearchAdapter(transport),
        }

    def register(self, provider: str, adapter: ResearchAdapter) -> None:
        key = provider.strip().lower()
        if not key:
            raise ResearchEngineError("Connector provider cannot be empty")
        self._adapters[key] = adapter

    def get(self, provider: str) -> ResearchAdapter:
        adapter = self._adapters.get(provider.strip().lower())
        if adapter is None:
            raise ResearchEngineError(f"Research provider is not installed: {provider}")
        return adapter

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def source_fingerprint(*, provider: str, uri: str | None, title: str, content: str) -> str:
    payload = "\n".join([provider.strip().lower(), uri or "", title.strip(), content.strip()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_existing_source(
    session: Session,
    *,
    research_session_id: UUID,
    content_sha256: str,
) -> ResearchSource | None:
    return session.scalar(
        select(ResearchSource).where(
            ResearchSource.research_session_id == research_session_id,
            ResearchSource.content_sha256 == content_sha256,
        )
    )


def ingest_research_document(
    session: Session,
    *,
    research_session: ResearchSession,
    actor_user_id: UUID,
    document: ResearchDocument,
    provider: str,
    connector_id: UUID | None = None,
) -> ResearchSource:
    fingerprint = source_fingerprint(
        provider=provider,
        uri=document.uri,
        title=document.title,
        content=document.content,
    )
    existing = _get_existing_source(
        session,
        research_session_id=research_session.id,
        content_sha256=fingerprint,
    )
    if existing is not None:
        return existing
    source = ResearchSource(
        organization_id=research_session.organization_id,
        research_session_id=research_session.id,
        connector_id=connector_id,
        created_by_user_id=actor_user_id,
        title=document.title,
        uri=document.uri,
        provider=provider,
        source_type=document.source_type,
        status=ResearchSourceStatus.CAPTURED.value,
        content=document.content,
        content_sha256=fingerprint,
        metadata_json=document.metadata or {},
        retrieved_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()
    knowledge = KnowledgeEntry(
        organization_id=research_session.organization_id,
        created_by_user_id=actor_user_id,
        title=document.title[:240],
        content=document.content,
        kind=KnowledgeKind.RESEARCH.value,
        tags=["research", provider.lower()],
        source_type=provider.lower(),
        source_uri=document.uri,
        source_label=document.title[:240],
        metadata_json={
            "research_session_id": str(research_session.id),
            "research_source_id": str(source.id),
            "connector_id": str(connector_id) if connector_id else None,
            "content_sha256": fingerprint,
            **(document.metadata or {}),
        },
    )
    session.add(knowledge)
    session.flush()
    source.knowledge_entry_id = knowledge.id
    source.status = ResearchSourceStatus.INGESTED.value
    record_audit(
        session,
        organization_id=research_session.organization_id,
        actor_user_id=actor_user_id,
        action="research.source.ingested",
        resource_type="research_source",
        resource_id=str(source.id),
        details={
            "research_session_id": str(research_session.id),
            "knowledge_entry_id": str(knowledge.id),
            "provider": provider,
        },
    )
    session.commit()
    session.refresh(source)
    return source


def _resolve_connector_credential(session: Session, connector: ResearchConnector) -> str | None:
    if connector.secret_reference_id is None:
        return None
    reference = session.scalar(
        select(SecretReference).where(
            SecretReference.id == connector.secret_reference_id,
            SecretReference.organization_id == connector.organization_id,
        )
    )
    if reference is None:
        raise ResearchEngineError("Connector runtime reference was not found")
    try:
        return resolve_secret(reference)
    except SecretVaultError as exc:
        raise ResearchEngineError(str(exc)) from exc


def execute_research_session(
    session: Session,
    *,
    research_session: ResearchSession,
    actor_user_id: UUID,
    connector_ids: list[UUID] | None = None,
    max_results_per_connector: int = 10,
    registry: ResearchConnectorRegistry | None = None,
    allow_approval_required: bool = False,
) -> list[ResearchSource]:
    if research_session.status == ResearchStatus.RUNNING.value:
        raise ResearchEngineError("Research session is already running")
    selected = connector_ids or [UUID(value) for value in research_session.connector_ids]
    if not selected:
        raise ResearchEngineError("At least one research connector is required")
    connectors = list(
        session.scalars(
            select(ResearchConnector).where(
                ResearchConnector.organization_id == research_session.organization_id,
                ResearchConnector.id.in_(selected),
            )
        )
    )
    if len(connectors) != len(set(selected)):
        raise ResearchEngineError("One or more research connectors were not found")
    research_session.status = ResearchStatus.RUNNING.value
    research_session.started_at = datetime.now(UTC)
    research_session.completed_at = None
    session.commit()
    connector_registry = registry or ResearchConnectorRegistry()
    captured: list[ResearchSource] = []
    failures: list[dict[str, str]] = []
    for connector in connectors:
        if connector.status != ConnectorStatus.ACTIVE.value:
            failures.append({"connector_id": str(connector.id), "error": "connector disabled"})
            continue
        if connector.approval_mode == "always" and not allow_approval_required:
            failures.append({"connector_id": str(connector.id), "error": "approval required"})
            continue
        try:
            adapter = connector_registry.get(connector.provider)
            runtime_config = dict(connector.config_json)
            runtime_config["_allowed_hosts"] = list(connector.allowed_hosts)
            runtime_config["_allowed_repositories"] = list(connector.allowed_repositories)
            runtime_config["_max_requests"] = connector.max_requests_per_run
            credential = _resolve_connector_credential(session, connector)
            documents = adapter.fetch(
                query=research_session.query,
                config=runtime_config,
                limit=min(max_results_per_connector, connector.max_requests_per_run),
                credential=credential,
            )
            for document in documents:
                captured.append(
                    ingest_research_document(
                        session,
                        research_session=research_session,
                        actor_user_id=actor_user_id,
                        document=document,
                        provider=connector.provider,
                        connector_id=connector.id,
                    )
                )
        except ResearchEngineError as exc:
            failures.append({"connector_id": str(connector.id), "error": str(exc)})
    research_session.completed_at = datetime.now(UTC)
    research_session.status = (
        ResearchStatus.COMPLETED.value if captured or not failures else ResearchStatus.FAILED.value
    )
    research_session.summary = {
        "source_count": len(captured),
        "connector_count": len(connectors),
        "failure_count": len(failures),
        "failures": failures,
    }
    record_audit(
        session,
        organization_id=research_session.organization_id,
        actor_user_id=actor_user_id,
        action="research.session.completed",
        resource_type="research_session",
        resource_id=str(research_session.id),
        details=research_session.summary,
    )
    session.commit()
    session.refresh(research_session)
    return captured
