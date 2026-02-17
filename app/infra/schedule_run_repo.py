from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Any, Dict

from django.db import transaction


@transaction.atomic
def save_schedule_run_from_out(
    tenant_name: str,
    out: Dict[str, Any],
    algorithm_version: str = "greedy_v1",
):
    from core.models import Assignment, Employee, ScheduleRun, Station, Tenant

    tenant = Tenant.objects.get(name=tenant_name)

    # 0) normalize date to python date
    raw_date = out.get("date")
    if isinstance(raw_date, date_type):
        day = raw_date
    else:
        # expect "YYYY-MM-DD"
        day = datetime.fromisoformat(str(raw_date)).date()

    # 1) normalize assignments keys WITHOUT mutating original out
    original_assignments = out.get("assignments") or {}
    normalized_assignments: Dict[str, Any] = {}
    station_order: list[str] = []

    for station_name, items in original_assignments.items():
        station_code = str(station_name).strip().lower()
        if not station_code:
            continue
        # 如果 normalize 後 key 重複，後面會覆蓋前面；這裡先保守處理：只記第一次順序
        if station_code not in normalized_assignments:
            station_order.append(station_code)
        normalized_assignments[station_code] = items

    # 2) create run (store meta + station_order)
    meta = {
        "warnings": out.get("warnings", []),
        "headcount_total": out.get("headcount_total"),
        "chefs_present": out.get("chefs_present"),
        "station_order": station_order,
    }

    run = ScheduleRun.objects.create(
        tenant=tenant,
        start_date=day,
        end_date=day,
        algorithm_version=algorithm_version,
        meta=meta,
    )

    # 3) overwrite assignments for that day (tenant+date)
    Assignment.objects.filter(
        tenant=tenant,
        date=day,
    ).delete()

    # 4) write new assignments
    for station_code in station_order:
        items = normalized_assignments.get(station_code) or []
        station = Station.objects.get(tenant=tenant, code=station_code)

        # items 可能是 list[dict] 或其他格式；這裡只處理 list[dict]
        if not isinstance(items, list):
            continue

        for rec in items:
            if not isinstance(rec, dict):
                continue

            employee = Employee.objects.get(tenant=tenant, name=rec["name"])

            notes_val = rec.get("notes", "")
            if isinstance(notes_val, list):
                notes_val = ",".join(map(str, notes_val))
            elif notes_val is None:
                notes_val = ""

            Assignment.objects.create(
                tenant=tenant,
                schedule_run=run,
                date=day,
                station=station,
                employee=employee,
                shift_code=rec.get("shift"),
                notes=str(notes_val),
            )

    return run
