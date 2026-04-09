from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Any, Dict

from django.db import transaction

from core.models import Assignment, Employee, ScheduleRun, Station, Tenant


class DailyRunPersistenceFixtureError(RuntimeError):
    def __init__(
        self,
        *,
        tenant_name: str,
        missing_station_codes: list[str] | None = None,
        missing_employee_names: list[str] | None = None,
    ) -> None:
        self.tenant_name = tenant_name
        self.missing_station_codes = list(missing_station_codes or [])
        self.missing_employee_names = list(missing_employee_names or [])

        parts: list[str] = []
        if self.missing_station_codes:
            parts.append(f"missing stations: {', '.join(self.missing_station_codes)}")
        if self.missing_employee_names:
            parts.append(f"missing employees: {', '.join(self.missing_employee_names)}")
        detail = "; ".join(parts) or "missing persistence fixtures"

        super().__init__(
            f"Daily-run persistence fixtures are incomplete for tenant '{tenant_name}': {detail}."
        )


@transaction.atomic
def save_schedule_run_from_out(
    tenant_name: str,
    out: Dict[str, Any],
    algorithm_version: str = "greedy_v1",
) -> ScheduleRun:
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

    employee_names_in_order: list[str] = []
    seen_employee_names: set[str] = set()
    for station_code in station_order:
        items = normalized_assignments.get(station_code) or []
        if not isinstance(items, list):
            continue

        for rec in items:
            if not isinstance(rec, dict) or "name" not in rec:
                continue

            employee_name = str(rec["name"])
            if employee_name in seen_employee_names:
                continue

            employee_names_in_order.append(employee_name)
            seen_employee_names.add(employee_name)

    stations_by_code = {
        station.code: station
        for station in Station.objects.filter(tenant=tenant, code__in=station_order)
    }
    employees_by_name = {
        employee.name: employee
        for employee in Employee.objects.filter(
            tenant=tenant,
            name__in=employee_names_in_order,
        )
    }

    missing_station_codes = [code for code in station_order if code not in stations_by_code]
    missing_employee_names = [
        name for name in employee_names_in_order if name not in employees_by_name
    ]
    if missing_station_codes or missing_employee_names:
        raise DailyRunPersistenceFixtureError(
            tenant_name=tenant_name,
            missing_station_codes=missing_station_codes,
            missing_employee_names=missing_employee_names,
        )

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

    # 3) write assignments for this run only
    for station_code in station_order:
        items = normalized_assignments.get(station_code) or []
        station = stations_by_code[station_code]

        # items 可能是 list[dict] 或其他格式；這裡只處理 list[dict]
        if not isinstance(items, list):
            continue

        for rec in items:
            if not isinstance(rec, dict):
                continue

            employee = employees_by_name[rec["name"]]

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
