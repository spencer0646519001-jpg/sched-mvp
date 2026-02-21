import json
from pathlib import Path


class ShiftDefsNotFound(Exception):
    pass


class ShiftDefsInvalid(Exception):
    pass


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[1] / candidate


def load_shift_defs(path: str = "data/shifts.json") -> list[dict]:
    resolved = _resolve_path(path)
    if not resolved.exists():
        raise ShiftDefsNotFound(f"Shift defs file not found: {resolved}")

    try:
        with resolved.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ShiftDefsInvalid(f"Invalid JSON in shift defs: {resolved}") from exc

    if not isinstance(data, list):
        raise ShiftDefsInvalid("Shift defs root must be a list")

    normalized: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            raise ShiftDefsInvalid("Each shift definition must be an object")
        normalized.append(item)

    return normalized


def build_shift_legend(shifts: list[dict]) -> dict[str, dict]:
    legend: dict[str, dict] = {
        "": {"label": "Unassigned"},
        "OFF": {"label": "Day off"},
    }

    for shift in shifts:
        code = str(shift.get("code", "")).strip()
        if not code:
            continue

        start = shift.get("start")
        end = shift.get("end")
        break_minutes = shift.get("break_minutes")
        paid_hours = shift.get("paid_hours")

        legend[code] = {
            "label": f"{start}-{end} ({paid_hours}h)",
            "start": start,
            "end": end,
            "break_minutes": break_minutes,
            "paid_hours": paid_hours,
        }

    return legend
