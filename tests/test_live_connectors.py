import pytest

from backend.app.services.research_engine import (
    GitHubResearchAdapter,
    PublicWebResearchAdapter,
    ResearchEngineError,
)


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        max_bytes: int,
    ) -> tuple[int, str, str]:
        assert timeout > 0
        assert max_bytes <= 1_000_000
        self.requests.append((url, headers))
        return 200, "text/plain", "Seldrune controlled research source"


def test_web_adapter_enforces_host_allow_list() -> None:
    transport = FakeTransport()
    adapter = PublicWebResearchAdapter(transport)
    documents = adapter.fetch(
        query="research",
        config={
            "urls": ["https://docs.example.com/research"],
            "_allowed_hosts": ["docs.example.com"],
            "_max_requests": 2,
        },
        limit=10,
    )
    assert len(documents) == 1
    assert documents[0].uri == "https://docs.example.com/research"
    assert len(transport.requests) == 1


def test_web_adapter_rejects_unapproved_host() -> None:
    adapter = PublicWebResearchAdapter(FakeTransport())
    with pytest.raises(ResearchEngineError, match="allow-list"):
        adapter.fetch(
            query="research",
            config={
                "urls": ["https://unapproved.example.net/research"],
                "_allowed_hosts": ["docs.example.com"],
                "_max_requests": 2,
            },
            limit=10,
        )


def test_github_adapter_enforces_repository_allow_list() -> None:
    transport = FakeTransport()
    adapter = GitHubResearchAdapter(transport)
    documents = adapter.fetch(
        query="sdk",
        config={
            "repositories": ["openai/openai-python"],
            "_allowed_repositories": ["openai/openai-python"],
            "_max_requests": 1,
        },
        limit=10,
    )
    assert len(documents) == 1
    assert documents[0].metadata == {
        "repository": "openai/openai-python",
        "content_type": "text/plain",
    }
    assert transport.requests[0][0].endswith("/repos/openai/openai-python/readme")


def test_github_adapter_rejects_unapproved_repository() -> None:
    adapter = GitHubResearchAdapter(FakeTransport())
    with pytest.raises(ResearchEngineError, match="allow-list"):
        adapter.fetch(
            query="sdk",
            config={
                "repositories": ["other/project"],
                "_allowed_repositories": ["openai/openai-python"],
                "_max_requests": 1,
            },
            limit=10,
        )
