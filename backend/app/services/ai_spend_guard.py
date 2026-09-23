from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.seldrune_gpt_message import SeldruneGPTMessage


class AISpendBudgetExceeded(RuntimeError):
    """Raised when a new AI operation would exceed a cumulative spend ceiling."""


@dataclass(frozen=True)
class AISpendSnapshot:
    daily_usd: float
    monthly_usd: float
    day_started_at: datetime
    month_started_at: datetime


def _utc_now(value: datetime | None = None) -> datetime:
    now = value or datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _sum_agent_spend(
    session: Session,
    *,
    organization_id: UUID,
    since: datetime,
) -> float:
    value = session.scalar(
        select(func.coalesce(func.sum(ModelInvocation.estimated_cost_usd), 0.0)).where(
            ModelInvocation.organization_id == organization_id,
            ModelInvocation.created_at >= since,
        )
    )
    return float(value or 0.0)


def _sum_direct_gpt_spend(
    session: Session,
    *,
    organization_id: UUID,
    since: datetime,
) -> float:
    value = session.scalar(
        select(func.coalesce(func.sum(SeldruneGPTMessage.estimated_cost_usd), 0.0)).where(
            SeldruneGPTMessage.organization_id == organization_id,
            SeldruneGPTMessage.role == "assistant",
            SeldruneGPTMessage.created_at >= since,
        )
    )
    return float(value or 0.0)


def current_ai_spend(
    session: Session,
    *,
    organization_id: UUID,
    now: datetime | None = None,
) -> AISpendSnapshot:
    current = _utc_now(now)
    day_started_at = current.replace(hour=0, minute=0, second=0, microsecond=0)
    month_started_at = day_started_at.replace(day=1)

    daily_usd = _sum_agent_spend(
        session,
        organization_id=organization_id,
        since=day_started_at,
    ) + _sum_direct_gpt_spend(
        session,
        organization_id=organization_id,
        since=day_started_at,
    )
    monthly_usd = _sum_agent_spend(
        session,
        organization_id=organization_id,
        since=month_started_at,
    ) + _sum_direct_gpt_spend(
        session,
        organization_id=organization_id,
        since=month_started_at,
    )

    return AISpendSnapshot(
        daily_usd=round(daily_usd, 8),
        monthly_usd=round(monthly_usd, 8),
        day_started_at=day_started_at,
        month_started_at=month_started_at,
    )


def ai_spend_budget_status(
    session: Session,
    *,
    organization_id: UUID,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, float | bool | str]:
    snapshot = current_ai_spend(
        session,
        organization_id=organization_id,
        now=now,
    )
    daily_remaining = max(settings.ai_daily_max_usd - snapshot.daily_usd, 0.0)
    monthly_remaining = max(settings.ai_monthly_max_usd - snapshot.monthly_usd, 0.0)
    daily_utilization = (
        snapshot.daily_usd / settings.ai_daily_max_usd
        if settings.ai_daily_max_usd > 0
        else 1.0
    )
    monthly_utilization = (
        snapshot.monthly_usd / settings.ai_monthly_max_usd
        if settings.ai_monthly_max_usd > 0
        else 1.0
    )
    return {
        "daily_spent_usd": round(snapshot.daily_usd, 6),
        "daily_limit_usd": round(settings.ai_daily_max_usd, 6),
        "daily_remaining_usd": round(daily_remaining, 6),
        "daily_utilization": round(daily_utilization, 4),
        "monthly_spent_usd": round(snapshot.monthly_usd, 6),
        "monthly_limit_usd": round(settings.ai_monthly_max_usd, 6),
        "monthly_remaining_usd": round(monthly_remaining, 6),
        "monthly_utilization": round(monthly_utilization, 4),
        "near_limit": (
            daily_utilization >= settings.ai_spend_warning_ratio
            or monthly_utilization >= settings.ai_spend_warning_ratio
        ),
        "timezone": "UTC",
    }


def enforce_ai_spend_budget(
    session: Session,
    *,
    organization_id: UUID,
    settings: Settings,
    projected_usd: float = 0.0,
    now: datetime | None = None,
) -> AISpendSnapshot:
    projected = max(float(projected_usd), 0.0)
    snapshot = current_ai_spend(
        session,
        organization_id=organization_id,
        now=now,
    )

    projected_daily = snapshot.daily_usd + projected
    if projected_daily > settings.ai_daily_max_usd:
        raise AISpendBudgetExceeded(
            "AI daily spend guard blocked this operation: "
            f"USD {snapshot.daily_usd:.4f} already recorded today + "
            f"up to USD {projected:.4f} projected exceeds the "
            f"USD {settings.ai_daily_max_usd:.4f} daily ceiling"
        )

    projected_monthly = snapshot.monthly_usd + projected
    if projected_monthly > settings.ai_monthly_max_usd:
        raise AISpendBudgetExceeded(
            "AI monthly spend guard blocked this operation: "
            f"USD {snapshot.monthly_usd:.4f} already recorded this month + "
            f"up to USD {projected:.4f} projected exceeds the "
            f"USD {settings.ai_monthly_max_usd:.4f} monthly ceiling"
        )

    return snapshot
