from unittest.mock import MagicMock
from uuid import uuid4

from backend.app.services.owner_push_delivery import PushDeliveryResult
from backend.app.services import owner_push_orchestration as orchestration


def test_same_fingerprint_is_suppressed_after_success(monkeypatch) -> None:
    orchestration._last_delivered_fingerprint.clear()
    session = MagicMock()
    subscription = MagicMock()
    session.scalars.return_value = [subscription]
    calls = []
    monkeypatch.setattr(orchestration, "delivery_configured", lambda: True)
    monkeypatch.setattr(
        orchestration,
        "send_owner_attention_push",
        lambda subscription, envelope: calls.append(envelope["fingerprint"])
        or PushDeliveryResult(delivered=True),
    )
    organization_id = uuid4()
    user_id = uuid4()
    envelope = {"fingerprint": "a" * 64, "notification": {"has_attention": True}}

    first = orchestration.deliver_owner_attention_pushes(
        session, organization_id, user_id, envelope
    )
    second = orchestration.deliver_owner_attention_pushes(
        session, organization_id, user_id, envelope
    )

    assert first.delivered == 1
    assert first.deduplicated is False
    assert second.deduplicated is True
    assert second.attempted == 0
    assert calls == ["a" * 64]


def test_changed_fingerprint_is_delivered(monkeypatch) -> None:
    orchestration._last_delivered_fingerprint.clear()
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]
    calls = []
    monkeypatch.setattr(orchestration, "delivery_configured", lambda: True)
    monkeypatch.setattr(
        orchestration,
        "send_owner_attention_push",
        lambda subscription, envelope: calls.append(envelope["fingerprint"])
        or PushDeliveryResult(delivered=True),
    )
    organization_id = uuid4()
    user_id = uuid4()

    orchestration.deliver_owner_attention_pushes(
        session, organization_id, user_id, {"fingerprint": "a" * 64}
    )
    second = orchestration.deliver_owner_attention_pushes(
        session, organization_id, user_id, {"fingerprint": "b" * 64}
    )

    assert second.delivered == 1
    assert second.deduplicated is False
    assert calls == ["a" * 64, "b" * 64]


def test_complete_failure_does_not_poison_retry(monkeypatch) -> None:
    orchestration._last_delivered_fingerprint.clear()
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]
    results = iter(
        [
            PushDeliveryResult(delivered=False, stale=False, status_code=503),
            PushDeliveryResult(delivered=True),
        ]
    )
    monkeypatch.setattr(orchestration, "delivery_configured", lambda: True)
    monkeypatch.setattr(
        orchestration, "send_owner_attention_push", lambda subscription, envelope: next(results)
    )
    organization_id = uuid4()
    user_id = uuid4()
    envelope = {"fingerprint": "c" * 64}

    first = orchestration.deliver_owner_attention_pushes(
        session, organization_id, user_id, envelope
    )
    second = orchestration.deliver_owner_attention_pushes(
        session, organization_id, user_id, envelope
    )

    assert first.failed == 1
    assert first.deduplicated is False
    assert second.delivered == 1
    assert second.deduplicated is False
