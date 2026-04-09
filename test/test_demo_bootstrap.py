import json
import os

import django
import pytest
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.test.utils import override_settings


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def _delete_demo_tenant_state():
    from core.models import (
        Assignment,
        Employee,
        EmployeeStationSkill,
        ScheduleRun,
        ShiftDefinition,
        Station,
        Tenant,
    )

    tenant = Tenant.objects.filter(name="demo_kitchen").first()
    if tenant is None:
        return

    Assignment.objects.filter(tenant=tenant).delete()
    ScheduleRun.objects.filter(tenant=tenant).delete()
    EmployeeStationSkill.objects.filter(tenant=tenant).delete()
    ShiftDefinition.objects.filter(tenant=tenant).delete()
    Employee.objects.filter(tenant=tenant).delete()
    Station.objects.filter(tenant=tenant).delete()
    tenant.delete()


def test_seed_demo_bootstraps_four_stations_and_twelve_employees_idempotently():
    _django_setup()

    from core.models import Employee, Station, Tenant

    expected_station_codes = {
        "gateau",
        "glaze_and_fruit",
        "mise_en_place",
        "petit_four",
    }
    expected_employee_names = {
        "Takahashi_chef",
        "Funatsu",
        "Spencer",
        "Chung",
        "Ishikawa",
        "Mochizuki",
        "Takai",
        "Tarutani",
        "Komura",
        "Kim",
        "Sera",
        "Miyazawa",
    }

    with transaction.atomic():
        _delete_demo_tenant_state()

        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)

        tenant = Tenant.objects.get(name="demo_kitchen")
        station_codes = set(
            Station.objects.filter(tenant=tenant).values_list("code", flat=True)
        )
        employee_rows = {
            row["name"]: row
            for row in Employee.objects.filter(tenant=tenant)
            .values("name", "role", "is_assignable")
        }

        assert station_codes == expected_station_codes
        assert set(employee_rows.keys()) == expected_employee_names
        assert len(employee_rows) == 12
        assert employee_rows["Takahashi_chef"] == {
            "name": "Takahashi_chef",
            "role": "chef",
            "is_assignable": False,
        }
        assert employee_rows["Funatsu"] == {
            "name": "Funatsu",
            "role": "chef",
            "is_assignable": False,
        }
        assert employee_rows["Spencer"] == {
            "name": "Spencer",
            "role": "staff",
            "is_assignable": True,
        }

        transaction.set_rollback(True)


def test_save_schedule_run_from_out_raises_structured_fixture_error_before_writing_run():
    _django_setup()

    from app.infra.schedule_run_repo import (
        DailyRunPersistenceFixtureError,
        save_schedule_run_from_out,
    )
    from core.models import Employee, ScheduleRun, Station, Tenant

    with transaction.atomic():
        _delete_demo_tenant_state()
        call_command("seed_demo", verbosity=0)

        tenant = Tenant.objects.get(name="demo_kitchen")
        Station.objects.filter(tenant=tenant, code="gateau").delete()
        Employee.objects.filter(tenant=tenant, name="Kim").delete()

        with pytest.raises(DailyRunPersistenceFixtureError) as exc_info:
            save_schedule_run_from_out(
                "demo_kitchen",
                {
                    "date": "2026-01-06",
                    "warnings": [],
                    "headcount_total": 1,
                    "chefs_present": [],
                    "assignments": {
                        "gateau": [
                            {
                                "name": "Kim",
                                "shift": "A",
                            }
                        ]
                    },
                },
            )

        assert exc_info.value.tenant_name == "demo_kitchen"
        assert exc_info.value.missing_station_codes == ["gateau"]
        assert exc_info.value.missing_employee_names == ["Kim"]
        assert ScheduleRun.objects.filter(tenant=tenant).count() == 0

        transaction.set_rollback(True)


def test_create_daily_run_translates_fixture_error_to_structured_conflict(monkeypatch):
    _django_setup()

    from app.infra.schedule_run_repo import DailyRunPersistenceFixtureError

    monkeypatch.setattr(
        "core.api_views_daily.run_daily_schedule",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DailyRunPersistenceFixtureError(
                tenant_name="demo_kitchen",
                missing_station_codes=["gateau"],
                missing_employee_names=["Kim"],
            )
        ),
    )

    payload = {"date": "2026-01-06", "absent": []}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/demo_kitchen/daily-runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 409
    body = json.loads(response.content.decode("utf-8"))
    assert body["ok"] is False
    assert body["error"]["code"] == "persistence_fixtures_incomplete"
    assert body["error"]["details"] == {
        "tenant_name": "demo_kitchen",
        "missing_station_codes": ["gateau"],
        "missing_employee_names": ["Kim"],
    }
