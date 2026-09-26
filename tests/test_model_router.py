from types import SimpleNamespace

import pytest

from backend.app.core.config import Settings
from backend.app.core.modeling import (
    ModelFileInput,
    ModelProvider,
    ModelRequest,
    ModelRouteCandidate,
    ModelRoutePerformanceEvidence,
)
from backend.app.services import model_gateway as gateway_module
from backend.app.services.model_gateway import (
    ModelGateway,
    ModelGatewayError,
    model_provider_capabilities,
)


def _compatible_settings() -> Settings:
    return Settings(
        model_provider="openai_compatible",
        model_default="local-general",
        model_compatible_base_url="http://localhost:11434/v1",
        model_compatible_api_key="local-test-key",
    )


def test_router_selects_first_allowed_candidate_with_required_capabilities() -> None:
    gateway = ModelGateway(_compatible_settings())
    decision = gateway.route(
        (
            ModelRouteCandidate(
                ModelProvider.OPENAI_COMPATIBLE,
                "local-general",
                priority=10,
            ),
            ModelRouteCandidate(
                ModelProvider.OPENAI,
                "gpt-5.6-sol",
                priority=20,
            ),
        ),
        required_capabilities=("text", "files"),
    )

    assert decision.provider is ModelProvider.OPENAI
    assert decision.model == "gpt-5.6-sol"
    assert decision.capabilities.files is True


def test_router_honors_provider_policy_and_fails_closed() -> None:
    gateway = ModelGateway(_compatible_settings())

    with pytest.raises(ModelGatewayError, match="No allowed model route"):
        gateway.route(
            (
                ModelRouteCandidate(
                    ModelProvider.OPENAI_COMPATIBLE,
                    "local-general",
                ),
                ModelRouteCandidate(
                    ModelProvider.OPENAI,
                    "gpt-5.6-sol",
                ),
            ),
            required_capabilities=("files",),
            allowed_providers=(ModelProvider.OPENAI_COMPATIBLE,),
        )


def test_provider_capability_contract_is_explicit() -> None:
    compatible = model_provider_capabilities(ModelProvider.OPENAI_COMPATIBLE)
    direct = model_provider_capabilities(ModelProvider.OPENAI)

    assert compatible.text is True
    assert compatible.structured_output is True
    assert compatible.images is False
    assert compatible.files is False
    assert compatible.reasoning is False
    assert direct.images is True
    assert direct.files is True
    assert direct.reasoning is True


def test_openai_compatible_adapter_normalizes_chat_completion(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                id="compat-response-1",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"ok":true}')
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=12,
                    completion_tokens=4,
                    total_tokens=16,
                ),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(gateway_module, "OpenAI", FakeOpenAI)
    gateway = ModelGateway(_compatible_settings())
    request = ModelRequest(
        provider=ModelProvider.OPENAI_COMPATIBLE,
        model="local-general",
        instructions="Return JSON.",
        input_text="Validate this payload.",
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        max_output_tokens=80,
    )

    result, latency_ms = gateway.generate(request)

    assert result.provider is ModelProvider.OPENAI_COMPATIBLE
    assert result.model == "local-general"
    assert result.output_text == '{"ok":true}'
    assert result.response_id == "compat-response-1"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 4
    assert result.usage.total_tokens == 16
    assert latency_ms >= 0
    assert captured["client"] == {
        "api_key": "local-test-key",
        "base_url": "http://localhost:11434/v1",
        "timeout": 60.0,
    }
    sent = captured["request"]
    assert isinstance(sent, dict)
    assert sent["model"] == "local-general"
    assert sent["max_tokens"] == 80
    assert sent["response_format"]["type"] == "json_schema"


def test_openai_compatible_adapter_rejects_unsupported_files_before_network(
    monkeypatch,
) -> None:
    called = False

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr(gateway_module, "OpenAI", FakeOpenAI)
    gateway = ModelGateway(_compatible_settings())
    request = ModelRequest(
        provider=ModelProvider.OPENAI_COMPATIBLE,
        model="local-general",
        input_text="Read attachment.",
        input_files=(
            ModelFileInput(
                filename="note.txt",
                data_base64="aGVsbG8=",
                media_type="text/plain",
            ),
        ),
    )

    with pytest.raises(ModelGatewayError, match="files"):
        gateway.generate(request)

    assert called is False


def test_openai_compatible_adapter_requires_endpoint_configuration() -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_default="local-general",
    )
    gateway = ModelGateway(settings)

    with pytest.raises(
        ModelGatewayError,
        match="SELDRUNE_MODEL_COMPATIBLE_BASE_URL",
    ):
        gateway.generate(
            ModelRequest(
                provider=ModelProvider.OPENAI_COMPATIBLE,
                model="local-general",
                input_text="hello",
            )
        )



def _performance(
    provider: ModelProvider,
    model: str,
    *,
    succeeded: bool,
    age_seconds: int,
    key: str,
    verified: bool = True,
) -> ModelRoutePerformanceEvidence:
    return ModelRoutePerformanceEvidence(
        provider=provider,
        model=model,
        succeeded=succeeded,
        age_seconds=age_seconds,
        evidence_key=key,
        evidence_refs=(f"evidence:{key}",),
        verified=verified,
    )


def test_recent_verified_performance_overrides_stale_static_priority() -> None:
    gateway = ModelGateway(_compatible_settings())
    candidates = (
        ModelRouteCandidate(
            ModelProvider.OPENAI_COMPATIBLE,
            "local-general",
            priority=10,
        ),
        ModelRouteCandidate(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            priority=20,
        ),
    )
    day = 24 * 60 * 60
    evidence = (
        *tuple(
            _performance(
                ModelProvider.OPENAI_COMPATIBLE,
                "local-general",
                succeeded=True,
                age_seconds=30 * day,
                key=f"local-stale-{index}",
            )
            for index in range(8)
        ),
        _performance(
            ModelProvider.OPENAI_COMPATIBLE,
            "local-general",
            succeeded=False,
            age_seconds=60 * 60,
            key="local-recent-fail-1",
        ),
        _performance(
            ModelProvider.OPENAI_COMPATIBLE,
            "local-general",
            succeeded=False,
            age_seconds=2 * 60 * 60,
            key="local-recent-fail-2",
        ),
        *tuple(
            _performance(
                ModelProvider.OPENAI,
                "gpt-5.6-sol",
                succeeded=False,
                age_seconds=30 * day,
                key=f"openai-stale-{index}",
            )
            for index in range(4)
        ),
        _performance(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            succeeded=True,
            age_seconds=60 * 60,
            key="openai-recent-success-1",
        ),
        _performance(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            succeeded=True,
            age_seconds=2 * 60 * 60,
            key="openai-recent-success-2",
        ),
    )

    decision = gateway.route(
        candidates,
        required_capabilities=("text",),
        performance_evidence=evidence,
    )

    assert decision.provider is ModelProvider.OPENAI
    assert decision.performance is not None
    assert decision.performance.recent_verified_samples == 2
    assert decision.performance.recent_success_rate == 1.0
    assert decision.performance.drift_detected is True
    assert decision.performance.trust_score is not None
    assert decision.performance.trust_score > 0.8


def test_stale_or_unverified_history_does_not_override_priority() -> None:
    gateway = ModelGateway(_compatible_settings())
    day = 24 * 60 * 60
    candidates = (
        ModelRouteCandidate(
            ModelProvider.OPENAI_COMPATIBLE,
            "local-general",
            priority=10,
        ),
        ModelRouteCandidate(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            priority=20,
        ),
    )
    evidence = (
        _performance(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            succeeded=True,
            age_seconds=30 * day,
            key="stale-success-1",
        ),
        _performance(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            succeeded=True,
            age_seconds=31 * day,
            key="stale-success-2",
        ),
        _performance(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            succeeded=True,
            age_seconds=60,
            key="unverified-success-1",
            verified=False,
        ),
        _performance(
            ModelProvider.OPENAI,
            "gpt-5.6-sol",
            succeeded=True,
            age_seconds=120,
            key="unverified-success-2",
            verified=False,
        ),
    )

    decision = gateway.route(
        candidates,
        performance_evidence=evidence,
    )

    assert decision.provider is ModelProvider.OPENAI_COMPATIBLE
    assert decision.performance is not None
    assert decision.performance.trust_score is None


def test_recent_evidence_is_deduplicated_and_negative_age_fails_closed() -> None:
    gateway = ModelGateway(_compatible_settings())
    candidate = ModelRouteCandidate(
        ModelProvider.OPENAI,
        "gpt-5.6-sol",
        priority=20,
    )
    duplicate = _performance(
        ModelProvider.OPENAI,
        "gpt-5.6-sol",
        succeeded=True,
        age_seconds=60,
        key="same-receipt",
    )
    decision = gateway.route(
        (candidate,),
        performance_evidence=(
            duplicate,
            duplicate,
            _performance(
                ModelProvider.OPENAI,
                "gpt-5.6-sol",
                succeeded=False,
                age_seconds=120,
                key="second-receipt",
            ),
        ),
    )

    assert decision.performance is not None
    assert decision.performance.recent_verified_samples == 2
    assert decision.performance.lifetime_verified_samples == 2

    with pytest.raises(ModelGatewayError, match="age cannot be negative"):
        gateway.route(
            (candidate,),
            performance_evidence=(
                _performance(
                    ModelProvider.OPENAI,
                    "gpt-5.6-sol",
                    succeeded=True,
                    age_seconds=-1,
                    key="invalid-age",
                ),
            ),
        )
