"""Persistence helpers for the canonical Django monthly workspace."""

from __future__ import annotations

from typing import Any

from core.models import MonthlyWorkspace, Tenant


def serialize_monthly_workspace(workspace: MonthlyWorkspace) -> dict[str, Any]:
    return {
        "tenant_name": workspace.tenant.name,
        "year_month": workspace.year_month,
        "leave_requests": dict(workspace.leave_requests or {}),
        "working_state": dict(workspace.working_state or {}),
        "revision": int(workspace.revision),
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
    }


def load_monthly_workspace(*, tenant_name: str, year_month: str) -> dict[str, Any] | None:
    workspace = (
        MonthlyWorkspace.objects.select_related("tenant")
        .filter(tenant__name=tenant_name, year_month=year_month)
        .first()
    )
    if workspace is None:
        return None
    return serialize_monthly_workspace(workspace)


def save_monthly_workspace(
    *,
    tenant_name: str,
    year_month: str,
    leave_requests: dict[str, list[str]],
    working_state: dict[str, Any],
) -> dict[str, Any]:
    tenant, _ = Tenant.objects.get_or_create(name=tenant_name)
    workspace, created = MonthlyWorkspace.objects.get_or_create(
        tenant=tenant,
        year_month=year_month,
        defaults={
            "leave_requests": dict(leave_requests or {}),
            "working_state": dict(working_state or {}),
            "revision": 1,
        },
    )
    if not created:
        workspace.leave_requests = dict(leave_requests or {})
        workspace.working_state = dict(working_state or {})
        workspace.revision = int(workspace.revision) + 1
        workspace.save(
            update_fields=[
                "leave_requests",
                "working_state",
                "revision",
                "updated_at",
            ]
        )

    return serialize_monthly_workspace(workspace)
