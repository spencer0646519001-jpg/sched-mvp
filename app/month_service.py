# app/month_service.py
from __future__ import annotations
from app.domain.normalize import normalize_engine_assignments
from typing import Any, Dict, List
from datetime import date, datetime, timedelta
from app.generate_day import greedy_assign


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
            norm_assignments, norm_errors = normalize_engine_assignments(raw_assignments)

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
