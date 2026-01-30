# app/domain/normalize.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple

ALLOWED_STATIONS = {
    "gateau",
    "petit_four",
    "glaze_and_fruit",
    "mise_en_place",
}

ALLOWED_SHIFTS = {"A", "B", "C", "D", "1", "2", "3", "4"}

STATION_SYNONYMS = {
    "GATEAU": "gateau",
    "gateau": "gateau",
    "petit_four": "petit_four",
    "glaze_and_fruit": "glaze_and_fruit",
    "mise_en_place": "mise_en_place",
}


def canonical_station(raw: str) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if s in STATION_SYNONYMS:
        return STATION_SYNONYMS[s]
    return s.lower()


def canonical_shift(raw: str) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    return s.upper()


def normalize_engine_assignments(
    assignments: Dict[str, Any],
) -> Tuple[Dict[str, List[dict]], List[Dict[str, Any]]]:
    """
    input (engine-friendly):
      { "GATEAU": [{"name":"A","shift":"1"}], ... }
    output:
      normalized_assignments, errors
    - station keys canonicalize + validate
    - item.shift canonicalize + validate
    - 不合法的 station / item 進 errors（該筆略過）
    """
    errors: List[Dict[str, Any]] = []
    normalized: Dict[str, List[dict]] = {}

    if not isinstance(assignments, dict):
        return {}, [
            {"type": "invalid_assignments_type", "value": type(assignments).__name__}
        ]

    for station_raw, items in assignments.items():
        station = canonical_station(station_raw)

        if station not in ALLOWED_STATIONS:
            errors.append(
                {
                    "type": "invalid_station",
                    "value": station_raw,
                    "canonical": station,
                }
            )
            continue

        if not isinstance(items, list):
            errors.append(
                {
                    "type": "invalid_station_items_type",
                    "station": station,
                    "value": type(items).__name__,
                }
            )
            continue

        out_items: List[dict] = []
        for it in items:
            if not isinstance(it, dict):
                errors.append(
                    {
                        "type": "invalid_assignment_item_type",
                        "station": station,
                        "value": type(it).__name__,
                    }
                )
                continue

            shift_raw = it.get("shift")
            shift = canonical_shift(shift_raw)

            if shift not in ALLOWED_SHIFTS:
                errors.append(
                    {
                        "type": "invalid_shift",
                        "station": station,
                        "name": it.get("name"),
                        "value": shift_raw,
                        "canonical": shift,
                    }
                )
                continue

            out_items.append({**it, "shift": shift})

        normalized[station] = out_items

    return normalized, errors
