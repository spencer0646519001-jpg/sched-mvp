import json
import os
import uuid

import django
from django.db import transaction
from django.test import RequestFactory


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def _create_history_fixture():
    from core.models import Employee, Station, Tenant

    tenant_name = f"history_test_{uuid.uuid4().hex[:8]}"
    tenant = Tenant.objects.create(name=tenant_name)

    Station.objects.create(
        tenant=tenant,
        code="gateau",
        display_name="Gateau",
        sort_order=10,
    )
    Station.objects.create(
        tenant=tenant,
        code="petit_four",
        display_name="Petit Four",
        sort_order=20,
    )

    Employee.objects.create(tenant=tenant, name="Alice")
    Employee.objects.create(tenant=tenant, name="Bob")

    return tenant_name


def _daily_out(date_str: str, *, alice_shift: str, bob_shift: str, note: str) -> dict:
    return {
        "date": date_str,
        "warnings": [],
        "headcount_total": 2,
        "chefs_present": [],
        "assignments": {
            "gateau": [
                {
                    "name": "Alice",
                    "shift": alice_shift,
                    "notes": note,
                }
            ],
            "petit_four": [
                {
                    "name": "Bob",
                    "shift": bob_shift,
                }
            ],
        },
    }


def _assignment_rows(presented_assignments: list[dict], station: str) -> list[dict]:
    for item in presented_assignments:
        if item.get("station") == station:
            return item.get("assignees") or []
    return []


def test_same_day_runs_keep_assignments_scoped_to_each_run():
    _django_setup()

    from app.infra.schedule_run_repo import save_schedule_run_from_out
    from app.run_service import build_out_from_run
    from core.models import Assignment, ScheduleRun

    tenant_name = _create_history_fixture()
    date_str = "2026-02-03"

    with transaction.atomic():
        run1 = save_schedule_run_from_out(
            tenant_name,
            _daily_out(date_str, alice_shift="A", bob_shift="B", note="first"),
        )
        run2 = save_schedule_run_from_out(
            tenant_name,
            _daily_out(date_str, alice_shift="C", bob_shift="D", note="second"),
        )

        assert ScheduleRun.objects.filter(
            tenant__name=tenant_name,
            start_date=date_str,
        ).count() == 2
        assert Assignment.objects.filter(schedule_run=run1).count() == 2
        assert Assignment.objects.filter(schedule_run=run2).count() == 2
        assert Assignment.objects.filter(
            tenant__name=tenant_name,
            date=date_str,
        ).count() == 4

        run1_out = build_out_from_run(run1)
        run2_out = build_out_from_run(run2)

        assert run1_out["assignments"]["gateau"] == [
            {"name": "Alice", "shift": "A", "notes": "first"}
        ]
        assert run2_out["assignments"]["gateau"] == [
            {"name": "Alice", "shift": "C", "notes": "second"}
        ]

        transaction.set_rollback(True)


def test_get_run_out_returns_original_assignments_after_newer_same_day_run():
    _django_setup()

    from app.infra.schedule_run_repo import save_schedule_run_from_out
    from core.api_views_daily import get_run_out

    tenant_name = _create_history_fixture()
    date_str = "2026-02-03"
    factory = RequestFactory()

    with transaction.atomic():
        run1 = save_schedule_run_from_out(
            tenant_name,
            _daily_out(date_str, alice_shift="A", bob_shift="B", note="first"),
        )
        save_schedule_run_from_out(
            tenant_name,
            _daily_out(date_str, alice_shift="C", bob_shift="D", note="second"),
        )

        response = get_run_out(factory.get(f"/api/runs/{run1.id}/out/"), run1.id)
        body = json.loads(response.content.decode("utf-8"))

        assert response.status_code == 200
        assert body["ok"] is True
        assert body["data"]["run_id"] == run1.id

        gateau_assignees = _assignment_rows(
            body["data"]["out"]["data"]["assignments"],
            "gateau",
        )
        assert gateau_assignees == [
            {"name": "Alice", "shift": "A", "notes": "first"}
        ]

        transaction.set_rollback(True)
