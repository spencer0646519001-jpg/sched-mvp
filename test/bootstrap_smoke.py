from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    state_dir = ROOT / "state"
    state_dir.mkdir(exist_ok=True)
    db_path = state_dir / "bootstrap_smoke.sqlite3"
    if db_path.exists():
        db_path.unlink()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.conf import settings

    settings.DATABASES["default"]["NAME"] = str(db_path)
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

    import django

    django.setup()

    from django.core.management import call_command
    from django.db import connections
    from django.test import Client
    from core.models import Employee, ScheduleRun, Station, Tenant

    try:
        call_command("migrate", interactive=False, verbosity=0)
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)

        tenant = Tenant.objects.get(name="demo_kitchen")
        station_codes = set(
            Station.objects.filter(tenant=tenant).values_list("code", flat=True)
        )
        employee_names = set(
            Employee.objects.filter(tenant=tenant).values_list("name", flat=True)
        )

        assert station_codes == {
            "gateau",
            "glaze_and_fruit",
            "mise_en_place",
            "petit_four",
        }
        assert employee_names == {
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

        client = Client(raise_request_exception=False)
        monthly_response = client.post(
            "/api/monthly/preview",
            data=json.dumps(
                {
                    "year_month": "2025-11",
                    "leave_requests": {},
                    "language": "en",
                }
            ),
            content_type="application/json",
        )
        assert monthly_response.status_code == 200

        daily_response = client.post(
            "/api/tenants/demo_kitchen/daily-runs/",
            data=json.dumps({"date": "2026-01-06", "absent": []}),
            content_type="application/json",
        )
        assert daily_response.status_code == 201
        daily_body = json.loads(daily_response.content.decode("utf-8"))
        run_id = daily_body["data"]["run_id"]

        assert ScheduleRun.objects.filter(tenant=tenant).count() == 1

        run_out_response = client.get(f"/api/runs/{run_id}/out/")
        assert run_out_response.status_code == 200
        run_out_body = json.loads(run_out_response.content.decode("utf-8"))
        assert run_out_body["ok"] is True
        assert run_out_body["data"]["run_id"] == run_id
    finally:
        connections.close_all()
        if db_path.exists():
            db_path.unlink()

    print("bootstrap smoke passed")


if __name__ == "__main__":
    main()
