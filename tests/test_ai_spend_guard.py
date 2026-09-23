from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.seldrune_gpt_message import SeldruneGPTMessage
from backend.app.services.ai_spend_guard import (
    AISpendBudgetExceeded,
    ai_spend_budget_status,
    current_ai_spend,
    enforce_ai_spend_budget,
)


def _session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return Session(engine), engine


def test_cumulative_spend_guard_sums_agent_and_direct_gpt_costs() -> None:
    session, engine = _session()
    organization_id = uuid4()
    now = datetime.now(UTC)
    try:
        session.add(
            SeldruneGPTMessage(
                organization_id=organization_id,
                user_id=uuid4(),
                role="assistant",
                content="metered direct response",
                estimated_cost_usd=0.4,
                model_calls=1,
                created_at=now,
            )
        )
        session.add(
            ModelInvocation(
                organization_id=organization_id,
                task_id=uuid4(),
                agent_id=uuid4(),
                provider="openai",
                model="gpt-5.6-luna",
                status="succeeded",
                estimated_cost_usd=0.3,
                created_at=now,
            )
        )
        session.commit()

        snapshot = current_ai_spend(
            session,
            organization_id=organization_id,
            now=now,
        )
        assert snapshot.daily_usd == pytest.approx(0.7)
        assert snapshot.monthly_usd == pytest.approx(0.7)

        settings = Settings(
            ai_daily_max_usd=1.0,
            ai_monthly_max_usd=5.0,
            ai_spend_warning_ratio=0.8,
        )
        status = ai_spend_budget_status(
            session,
            organization_id=organization_id,
            settings=settings,
            now=now,
        )
        assert status["daily_remaining_usd"] == pytest.approx(0.3)
        assert status["monthly_remaining_usd"] == pytest.approx(4.3)
        assert status["near_limit"] is False

        enforce_ai_spend_budget(
            session,
            organization_id=organization_id,
            settings=settings,
            projected_usd=0.2,
            now=now,
        )
        with pytest.raises(AISpendBudgetExceeded, match="daily spend guard"):
            enforce_ai_spend_budget(
                session,
                organization_id=organization_id,
                settings=settings,
                projected_usd=0.31,
                now=now,
            )
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_cumulative_spend_guard_blocks_monthly_ceiling() -> None:
    session, engine = _session()
    organization_id = uuid4()
    now = datetime.now(UTC)
    try:
        session.add(
            SeldruneGPTMessage(
                organization_id=organization_id,
                user_id=uuid4(),
                role="assistant",
                content="metered direct response",
                estimated_cost_usd=1.9,
                model_calls=1,
                created_at=now,
            )
        )
        session.commit()

        settings = Settings(
            ai_daily_max_usd=2.0,
            ai_monthly_max_usd=2.0,
        )
        with pytest.raises(AISpendBudgetExceeded, match="monthly spend guard"):
            enforce_ai_spend_budget(
                session,
                organization_id=organization_id,
                settings=settings,
                projected_usd=0.11,
                now=now,
            )
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
