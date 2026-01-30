# app/month_service.py
from __future__ import annotations
from app.domain.normalize import normalize_engine_assignments
from typing import Any, Dict, List, Tuple, Optional
from datetime import date as date_type, datetime, timedelta
from app.generate_day import greedy_assign
from django.db import transaction
from django.utils import timezone
from core.models import (
    Tenant,
    Station,
    Employee,
    ScheduleRun,
    Assignment,
    EmployeeStationSkill,
)

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month_end(d: date) -> date:
    # next month first day - 1 day
    if d.month == 12:
        nm = date(d.year + 1, 1, 1)
    else:
        nm = date(d.year, d.month + 1, 1)
    return nm - timedelta(days=1)


def build_month(start_date: str) -> Dict[str, Any]:
    if not start_date or not start_date.strip():
        return {"success": False, "errors": ["MISSING_START_DATE"]}

    try:
        start = _parse_date(start_date)
    except Exception:
        return {"success": False, "errors": ["INVALID_START_DATE_FORMAT"]}

    end = _month_end(start)

    days: List[Dict[str, Any]] = []
    cur = start
    while cur <= end:
        cur_str = cur.strftime("%Y-%m-%d")
        try:
            plan = greedy_assign(cur_str, absent=[])

            # --- B2: canonicalize assignments at the source (month boundary) ---
            raw_assignments = plan.get("assignments", {})
            norm_assignments, norm_errors = normalize_engine_assignments(
                raw_assignments
            )

            day_errors: List[str] = []
            # greedy_assign 可能本來就有 errors（若沒有就忽略）
            if isinstance(plan.get("errors"), list):
                day_errors.extend([str(x) for x in plan.get("errors")])

            # normalize_engine_assignments 回的是 list[dict]，先轉成可讀字串（先不改 errors schema）
            day_errors.extend([f"NORMALIZE:{e['type']}" for e in norm_errors])

            days.append(
                {
                    "date": cur_str,
                    "success": True,
                    "errors": day_errors,
                    "assignments": norm_assignments,
                }
            )
        except Exception as e:
            days.append(
                {
                    "date": cur_str,
                    "success": False,
                    "errors": [f"DAY_FAILED: {str(e)}"],
                    "assignments": {},
                }
            )
        cur += timedelta(days=1)

    meta = _month_rows(days)

    return {
        "success": True,
        "start_date": start_date,
        "days": days,
        "rows": meta["rows"],
        "stations": meta["stations"],
        "errors": [],
    }


def _month_rows(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    # stations：把整月出現過的 station 統一列出（前端用來排欄位）
    station_set = set()
    rows: List[Dict[str, Any]] = []

    for d in days:
        date_str = d.get("date")
        assignments = d.get("assignments", {}) or {}
        for station, entries in assignments.items():
            station_set.add(station)
            for e in entries or []:
                rows.append(
                    {
                        "date": date_str,
                        "station": station,
                        "name": e.get("name", ""),
                        "shift": e.get("shift", ""),
                    }
                )

    stations = sorted(station_set)
    return {"rows": rows, "stations": stations}


def build_station_map_from_db(tenant_name: str) -> Dict[str, List[str]]:
    tenant = Tenant.objects.get(name=tenant_name)

    stations = (
        Station.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("sort_order", "code")
    )

    station_map: Dict[str, List[str]] = {}

    for st in stations:
        skills = (
            EmployeeStationSkill.objects
            .filter(tenant=tenant, station=st, employee__is_assignable=True, employee__is_active=True)
            .order_by("-level")
        )
        station_map[st.code] = [s.employee.name for s in skills]

    return station_map



def assign_from_db(tenant_name: str, strategy: str = "mini_candidate") -> Tuple[Dict[str, str], List[str]]:
    station_map = build_station_map_from_db(tenant_name)

    # 用你現在真正存在的引擎：greedy_assign
    schedule, warnings = greedy_assign(station_map, strategy=strategy)



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


def run_daily_schedule(
    tenant_name: str,
    date_str: str,
    absent: Optional[List[str]] = None,
    algorithm_version: str = "greedy_v1",
) -> ScheduleRun:
    from app.generate_day import greedy_assign  # 避免 circular import
    out = greedy_assign(date_str, absent=absent or [])
    run = save_schedule_run_from_out(
        tenant_name=tenant_name,
        out=out,
        algorithm_version=algorithm_version,
    )
    return run
