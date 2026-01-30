from __future__ import annotations

from typing import Dict, Any, List

from core.models import Tenant, ScheduleRun, Assignment


def build_out_from_run(run: ScheduleRun) -> Dict[str, Any]:
    """
    把 DB 裡的一次 ScheduleRun 還原成 engine out 風格 dict：
    {
      "date": "YYYY-MM-DD",
      "warnings": [...],
      "headcount_total": int,
      "chefs_present": [...],
      "assignments": {
          "gateau": [{"name": "...", "shift": "...", "notes": "..."}],
          ...
      }
    }
    """
    meta = run.meta or {}

    sd = run.start_date
    date_str = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)

    # ✅ 重要：用 meta 裡的 station_order 來還原「站位順序」
    station_order = meta.get("station_order") or []

    # ❌ 不要再用 station__code 排序（會把引擎決策順序洗掉）
    qs = (
        Assignment.objects
        .filter(schedule_run=run)
        .select_related("station", "employee")
        .order_by("date", "id")
    )

    # 先把資料撈成 station_code -> list[rec]
    tmp: Dict[str, List[Dict[str, Any]]] = {}
    for a in qs:
        station_code = a.station.code

        rec: Dict[str, Any] = {
            "name": a.employee.name,
            "shift": a.shift_code,
        }
        if a.notes:
            rec["notes"] = a.notes

        tmp.setdefault(station_code, []).append(rec)

    # 再依 station_order 組回 assignments dict（保留順序）
    assignments: Dict[str, List[Dict[str, Any]]] = {}

    if isinstance(station_order, list) and station_order:
        # 先照 station_order 排
        for code in station_order:
            code_s = str(code).strip().lower()
            if not code_s:
                continue
            if code_s in tmp:
                assignments[code_s] = tmp[code_s]

        # 把 DB 有、但不在 station_order 裡的補到最後（保險）
        for code, items in tmp.items():
            if code not in assignments:
                assignments[code] = items
    else:
        # station_order 不存在時，退回用 tmp（此時順序不保證，但至少不再字母排序）
        assignments = tmp

    out: Dict[str, Any] = {
        "date": date_str,
        "warnings": meta.get("warnings", []),
        "headcount_total": meta.get("headcount_total"),
        "chefs_present": meta.get("chefs_present", []),
        "assignments": assignments,
    }
    return out


def build_out_from_latest_run(tenant_name: str) -> Dict[str, Any]:
    tenant = Tenant.objects.get(name=tenant_name)
    run = ScheduleRun.objects.filter(tenant=tenant).order_by("-id").first()
    if run is None:
        raise ValueError(f"No ScheduleRun for tenant={tenant_name}")
    return build_out_from_run(run)
