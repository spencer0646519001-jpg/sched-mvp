# app/domain/patch_guard.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple

from app.domain.normalize import (
    canonical_station,
    canonical_shift,
    ALLOWED_STATIONS,
    ALLOWED_SHIFTS,
)


def build_canonical_patch(
    *,
    plan_date: str,
    parsed: Dict[str, Any],
    people_names: List[str],
) -> Tuple[Dict[str, str] | None, List[str]]:
    errors: List[str] = []

    name = (parsed.get("name") or "").strip()
    station_raw = parsed.get("station")
    shift_raw = parsed.get("shift")

    station = canonical_station(station_raw)
    shift = canonical_shift(shift_raw)

    if not name:
        errors.append("PATCH_MISSING_NAME")
    elif name not in set(people_names):
        errors.append("PATCH_UNKNOWN_NAME")

    if not station:
        errors.append("PATCH_MISSING_STATION")
    elif station not in ALLOWED_STATIONS:
        errors.append("PATCH_INVALID_STATION")

    if not shift:
        errors.append("PATCH_MISSING_SHIFT")
    elif shift not in ALLOWED_SHIFTS:
        errors.append("PATCH_INVALID_SHIFT")

    if errors:
        return None, errors

    patch = {
        "date": plan_date,  # date 永遠用 plan 的，不信任 LLM
        "name": name,
        "station": station,
        "shift": shift,
    }
    return patch, []
