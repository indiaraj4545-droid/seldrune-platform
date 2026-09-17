from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, case, func, select

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.membership import Membership
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.organization_kernel import OrganizationProject
from backend.app.models.task import Task
from backend.app.schemas.billing import (
    BillingDepartmentUsageBreakdown,
    BillingInvocationPage,
    BillingInvocationPublic,
    BillingProjectUsageBreakdown,
    BillingUsageBreakdown,
    BillingUsageSummary,
    BillingUsageTotals,
    ProjectAccountingCorrection,
)
from backend.app.schemas.organization_kernel import ProjectPublic
from backend.app.services.audit import record_audit

router = APIRouter(prefix="/organizations/{organization_id}/billing", tags=["billing"])
billing_read_dependency = require_org_permission(Permission.BILLING_READ)
billing_manage_dependency = require_org_permission(Permission.BILLING_MANAGE)
BillingReadDep = Annotated[Membership, Depends(billing_read_dependency)]
BillingManageDep = Annotated[Membership, Depends(billing_manage_dependency)]


def _apply_filters(
    statement: Select,
    *,
    provider: str | None,
    model: str | None,
    invocation_status: str | None,
    agent_id: UUID | None,
    task_id: UUID | None,
    project_id: UUID | None,
    department_id: UUID | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> Select:
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="created_from must be before or equal to created_to",
        )
    if provider is not None:
        statement = statement.where(ModelInvocation.provider == provider)
    if model is not None:
        statement = statement.where(ModelInvocation.model == model)
    if invocation_status is not None:
        statement = statement.where(ModelInvocation.status == invocation_status)
    if agent_id is not None:
        statement = statement.where(ModelInvocation.agent_id == agent_id)
    if task_id is not None:
        statement = statement.where(ModelInvocation.task_id == task_id)
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
    if department_id is not None:
        statement = statement.where(OrganizationProject.department_id == department_id)
    if created_from is not None:
        statement = statement.where(ModelInvocation.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(ModelInvocation.created_at <= created_to)
    return statement


def _attributed_base(organization_id: UUID) -> Select:
    return (
        select(ModelInvocation)
        .join(Task, Task.id == ModelInvocation.task_id)
        .outerjoin(OrganizationProject, OrganizationProject.id == Task.project_id)
        .where(ModelInvocation.organization_id == organization_id)
    )


def _usage_columns(filtered):
    return (
        func.count(filtered.c.id),
        func.coalesce(func.sum(filtered.c.total_tokens), 0),
        func.coalesce(
            func.sum(case((filtered.c.estimated_cost_usd.is_not(None), 1), else_=0)), 0
        ),
        func.coalesce(
            func.sum(case((filtered.c.estimated_cost_usd.is_(None), 1), else_=0)), 0
        ),
        func.coalesce(func.sum(filtered.c.estimated_cost_usd), 0.0),
    )


@router.get("/invocations", response_model=BillingInvocationPage)
def list_billing_invocations(
    organization_id: UUID,
    _membership: BillingReadDep,
    session: SessionDep,
    provider: str | None = Query(default=None, min_length=1, max_length=40),
    model: str | None = Query(default=None, min_length=1, max_length=160),
    invocation_status: str | None = Query(
        default=None,
        alias="status",
        min_length=1,
        max_length=32,
    ),
    agent_id: UUID | None = None,
    task_id: UUID | None = None,
    project_id: UUID | None = None,
    department_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BillingInvocationPage:
    statement = _attributed_base(organization_id)
    statement = _apply_filters(
        statement,
        provider=provider,
        model=model,
        invocation_status=invocation_status,
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        department_id=department_id,
        created_from=created_from,
        created_to=created_to,
    )
    rows = list(
        session.scalars(
            statement.order_by(ModelInvocation.created_at.desc(), ModelInvocation.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    items = [BillingInvocationPublic.model_validate(row) for row in rows]
    return BillingInvocationPage(items=items, limit=limit, offset=offset, returned=len(items))


@router.get("/usage-summary", response_model=BillingUsageSummary)
def get_billing_usage_summary(
    organization_id: UUID,
    _membership: BillingReadDep,
    session: SessionDep,
    provider: str | None = Query(default=None, min_length=1, max_length=40),
    model: str | None = Query(default=None, min_length=1, max_length=160),
    invocation_status: str | None = Query(
        default=None,
        alias="status",
        min_length=1,
        max_length=32,
    ),
    agent_id: UUID | None = None,
    task_id: UUID | None = None,
    project_id: UUID | None = None,
    department_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> BillingUsageSummary:
    base = (
        select(
            ModelInvocation,
            Task.project_id.label("project_id"),
            OrganizationProject.department_id.label("department_id"),
        )
        .join(Task, Task.id == ModelInvocation.task_id)
        .outerjoin(OrganizationProject, OrganizationProject.id == Task.project_id)
        .where(ModelInvocation.organization_id == organization_id)
    )
    base = _apply_filters(
        base,
        provider=provider,
        model=model,
        invocation_status=invocation_status,
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        department_id=department_id,
        created_from=created_from,
        created_to=created_to,
    )
    filtered = base.subquery()

    totals_row = session.execute(
        select(
            func.count(filtered.c.id),
            func.coalesce(func.sum(case((filtered.c.status == "succeeded", 1), else_=0)), 0),
            func.coalesce(func.sum(case((filtered.c.status == "failed", 1), else_=0)), 0),
            func.coalesce(func.sum(case((filtered.c.status == "running", 1), else_=0)), 0),
            func.coalesce(func.sum(filtered.c.input_tokens), 0),
            func.coalesce(func.sum(filtered.c.output_tokens), 0),
            func.coalesce(func.sum(filtered.c.total_tokens), 0),
            func.coalesce(
                func.sum(case((filtered.c.estimated_cost_usd.is_not(None), 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((filtered.c.estimated_cost_usd.is_(None), 1), else_=0)), 0
            ),
            func.coalesce(func.sum(filtered.c.estimated_cost_usd), 0.0),
            func.avg(filtered.c.latency_ms),
        )
    ).one()

    breakdown_rows = session.execute(
        select(
            filtered.c.provider,
            filtered.c.model,
            *_usage_columns(filtered),
        )
        .group_by(filtered.c.provider, filtered.c.model)
        .order_by(filtered.c.provider.asc(), filtered.c.model.asc())
    ).all()
    project_rows = session.execute(
        select(
            filtered.c.project_id,
            filtered.c.department_id,
            *_usage_columns(filtered),
        )
        .group_by(filtered.c.project_id, filtered.c.department_id)
        .order_by(filtered.c.project_id.asc().nullsfirst())
    ).all()
    department_rows = session.execute(
        select(
            filtered.c.department_id,
            *_usage_columns(filtered),
        )
        .group_by(filtered.c.department_id)
        .order_by(filtered.c.department_id.asc().nullsfirst())
    ).all()

    totals = BillingUsageTotals(
        invocation_count=int(totals_row[0] or 0),
        succeeded_count=int(totals_row[1] or 0),
        failed_count=int(totals_row[2] or 0),
        running_count=int(totals_row[3] or 0),
        input_tokens=int(totals_row[4] or 0),
        output_tokens=int(totals_row[5] or 0),
        total_tokens=int(totals_row[6] or 0),
        priced_invocation_count=int(totals_row[7] or 0),
        unpriced_invocation_count=int(totals_row[8] or 0),
        known_estimated_cost_usd=float(totals_row[9] or 0.0),
        average_latency_ms=float(totals_row[10]) if totals_row[10] is not None else None,
    )
    breakdowns = [
        BillingUsageBreakdown(
            provider=str(row[0]),
            model=str(row[1]),
            invocation_count=int(row[2] or 0),
            total_tokens=int(row[3] or 0),
            priced_invocation_count=int(row[4] or 0),
            unpriced_invocation_count=int(row[5] or 0),
            known_estimated_cost_usd=float(row[6] or 0.0),
        )
        for row in breakdown_rows
    ]
    by_project = [
        BillingProjectUsageBreakdown(
            project_id=row[0],
            department_id=row[1],
            invocation_count=int(row[2] or 0),
            total_tokens=int(row[3] or 0),
            priced_invocation_count=int(row[4] or 0),
            unpriced_invocation_count=int(row[5] or 0),
            known_estimated_cost_usd=float(row[6] or 0.0),
        )
        for row in project_rows
    ]
    by_department = [
        BillingDepartmentUsageBreakdown(
            department_id=row[0],
            invocation_count=int(row[1] or 0),
            total_tokens=int(row[2] or 0),
            priced_invocation_count=int(row[3] or 0),
            unpriced_invocation_count=int(row[4] or 0),
            known_estimated_cost_usd=float(row[5] or 0.0),
        )
        for row in department_rows
    ]
    return BillingUsageSummary(
        totals=totals,
        by_provider_model=breakdowns,
        by_project=by_project,
        by_department=by_department,
    )


@router.patch("/projects/{project_id}/accounting", response_model=ProjectPublic)
def correct_project_accounting(
    organization_id: UUID,
    project_id: UUID,
    payload: ProjectAccountingCorrection,
    _membership: BillingManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> OrganizationProject:
    project = session.scalar(
        select(OrganizationProject).where(
            OrganizationProject.id == project_id,
            OrganizationProject.organization_id == organization_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    before = {
        "budget_spent_usd": project.budget_spent_usd,
        "unpriced_model_invocation_count": project.unpriced_model_invocation_count,
    }
    if payload.budget_spent_usd is not None:
        project.budget_spent_usd = payload.budget_spent_usd
    if payload.unpriced_model_invocation_count is not None:
        project.unpriced_model_invocation_count = payload.unpriced_model_invocation_count
    after = {
        "budget_spent_usd": project.budget_spent_usd,
        "unpriced_model_invocation_count": project.unpriced_model_invocation_count,
    }
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="billing.project_accounting_corrected",
        resource_type="organization_project",
        resource_id=str(project.id),
        details={"before": before, "after": after, "reason": payload.reason},
    )
    session.commit()
    session.refresh(project)
    return project
