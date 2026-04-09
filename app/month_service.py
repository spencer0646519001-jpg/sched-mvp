"""Helpers retained for legacy calendar mirrors and the canonical daily-run write path."""

from __future__ import annotations

from app.domain.normalize import normalize_engine_assignments
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
from app.generate_day import greedy_assign, greedy_assign_with_inputs
from app.infra.engine_input_resolver import resolve_engine_inputs_for_tenant

from app.infra.schedule_run_repo import save_schedule_run_from_out as save_schedule_run_from_out_repo


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
            # Preserve engine-emitted errors when present.
            if isinstance(plan.get("errors"), list):
                day_errors.extend([str(x) for x in plan.get("errors")])

            # Keep normalization errors readable without changing the legacy payload shape.
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
    # Collect every station seen in the month so legacy calendar exports stay tabular.
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


def save_schedule_run_from_out(
    tenant_name: str,
    out: Dict[str, Any],
    algorithm_version: str = "greedy_v1",
):
    return save_schedule_run_from_out_repo(
        tenant_name=tenant_name,
        out=out,
        algorithm_version=algorithm_version,
    )


def run_daily_schedule(
    tenant_name: str,
    date_str: str,
    absent: Optional[List[str]] = None,
    algorithm_version: str = "greedy_v1",
) -> ScheduleRun:
    inputs = resolve_engine_inputs_for_tenant(tenant_name)
    out = greedy_assign_with_inputs(date_str, absent=absent or [], inputs=inputs)
    run = save_schedule_run_from_out(
        tenant_name=tenant_name,
        out=out,
        algorithm_version=algorithm_version,
    )
    return run
