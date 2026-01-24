from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


ENGINE_VERSION = "0.1"


def iso_now_jst() -> str:
    # JST = UTC+9 (固定，不考慮 DST)
    jst = timezone.utc.__class__(timezone.utc.utcoffset(None))  # placeholder guard
    jst = timezone(offset=timezone.utc.utcoffset(None) or timezone.utc.utcoffset(None))
    # 上面這種寫法太繞；用明確 offset
    from datetime import timedelta
    jst = timezone(timedelta(hours=9))
    return datetime.now(tz=jst).isoformat(timespec="seconds")


def present_run_out(
    *,
    date: str,
    out: Dict[str, Any],
    engine_version: str = ENGINE_VERSION,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Presenter: 將 engine 的 out 轉成固定 API schema。
    不改 engine，只在這裡做 mapping / normalize。
    """

    schedule = out.get("schedule") or out.get("assignments") or {}
    warnings = out.get("warnings") or []

    assignments = _normalize_assignments(schedule)
    warnings_norm = _normalize_warnings(warnings)

    return {
        "ok": True,
        "data": {
            "date": date,
            "assignments": assignments,
            "warnings": warnings_norm,
        },
        "meta": {
            "engine_version": engine_version,
            "generated_at": generated_at or iso_now_jst(),
        },
    }


def _normalize_assignments(schedule: Any) -> List[Dict[str, Any]]:
    """
    支援常見輸出：
    1) dict: {"gateau": "Kim", "petit_four": "Chung"}
    2) dict: {"gateau": [{"name":"Kim","shift":"A"}, ...], ...}
    3) list: [{"station":"gateau","person":"Kim"}, ...]
    4) list: [{"station":"gateau","assignees":[...]} , ...]
    統一輸出：
      {"station": str, "primary_person": str, "assignees": list}
    """
    if schedule is None:
        return []

    # case: list of dict rows
    if isinstance(schedule, list):
        out: List[Dict[str, Any]] = []
        for item in schedule:
            if not isinstance(item, dict):
                continue
            station = str(item.get("station", "")).strip()
            if not station:
                continue

            # accept either "person" or "assignees"
            person_val = item.get("person")
            assignees_val = item.get("assignees")

            primary_person, assignees = _extract_primary_and_assignees(
                assignees_val if assignees_val is not None else person_val
            )

            out.append({
                "station": station,
                "primary_person": primary_person,
                "assignees": assignees,
            })
        return out

    # case: dict station -> value
    if isinstance(schedule, dict):
        out: List[Dict[str, Any]] = []
        for station, val in schedule.items():
            station_s = str(station).strip()
            if not station_s:
                continue

            primary_person, assignees = _extract_primary_and_assignees(val)

            out.append({
                "station": station_s,
                "primary_person": primary_person,
                "assignees": assignees,
            })
        return out

    return []


def _extract_primary_and_assignees(val: Any) -> tuple[str, list]:
    """
    val 可能是：
    - "Kim"
    - {"name":"Kim","shift":"A"}
    - [{"name":"Kim","shift":"A"}, {"name":"Masuda","shift":"B"}]
    - 其他型別（保守轉字串）
    回傳： (primary_person, assignees_list)
    """
    if val is None:
        return ("", [])

    # string person
    if isinstance(val, str):
        s = val.strip()
        return (s, [] if not s else [{"name": s}])

    # dict person
    if isinstance(val, dict):
        name = str(val.get("name", "")).strip() if "name" in val else ""
        primary = name or (str(val) if val else "")
        return (primary, [val])

    # list of dict persons
    if isinstance(val, list):
        assignees = [x for x in val if isinstance(x, dict)]
        if assignees:
            name = str(assignees[0].get("name", "")).strip()
            primary = name or ""
            return (primary, assignees)
        # list but not dicts: stringify
        s = str(val)
        return (s, [])

    # fallback: stringify
    s = str(val).strip()
    return (s, [] if not s else [{"name": s}])


def _normalize_warnings(warnings: Any) -> List[Dict[str, str]]:
    """
    你可能有：
    - list[str]
    - list[dict] e.g. {"station": "...", "missing": 1}
    - list[station] 等等
    這裡統一成：{code, station, message}
    """
    if not warnings:
        return []

    out: List[Dict[str, str]] = []

    if isinstance(warnings, list):
        for w in warnings:
            if isinstance(w, str):
                out.append({
                    "code": "WARNING",
                    "station": "",
                    "message": w,
                })
                continue

            if isinstance(w, dict):
                station = str(w.get("station", "")).strip()
                # 優先給比較穩定的 code
                code = str(w.get("code") or "WARNING").strip()
                # message 統一給人讀的字串
                if "message" in w and w["message"] is not None:
                    message = str(w["message"]).strip()
                else:
                    message = _dict_to_message(w)
                out.append({
                    "code": code,
                    "station": station,
                    "message": message,
                })
                continue

            # 其他型別：轉字串塞 message
            out.append({
                "code": "WARNING",
                "station": "",
                "message": str(w),
            })

        return out

    # 非 list：直接轉字串
    return [{
        "code": "WARNING",
        "station": "",
        "message": str(warnings),
    }]


def _dict_to_message(d: Dict[str, Any]) -> str:
    # 最小可讀性組裝：避免前端看到一坨 dict
    parts = []
    for k in ("station", "required", "assigned", "missing"):
        if k in d:
            parts.append(f"{k}={d.get(k)}")
    if parts:
        return ", ".join(parts)
    # fallback：只列出 key
    return "warning: " + ", ".join(sorted(map(str, d.keys())))
