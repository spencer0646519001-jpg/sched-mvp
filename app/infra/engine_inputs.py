"""Scheduler engine input builders.

Current architecture truth:
- the demo scheduler is JSON-canonical today
- ``build_inputs_from_json()`` is the canonical builder for demo scheduling flows
- DB-backed helpers in this module are retained for non-canonical helper paths and
  should not be read as a completed scheduler-input migration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.infra.json_loader import load_calendar, load_rules, load_shifts, load_workers

if TYPE_CHECKING:
    from app.generate_day import EngineInputs


def _normalize_station_key(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_people_station_skills(people: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for p in people:
        if not isinstance(p, dict):
            continue
        copied = dict(p)
        raw_skills = copied.get("station_skills") or []
        copied["station_skills"] = [
            _normalize_station_key(code) for code in raw_skills if _normalize_station_key(code)
        ]
        normalized.append(copied)
    return normalized


def build_inputs_from_db(tenant_name: str) -> "EngineInputs":
    """Build engine inputs from DB-backed read helpers.

    This helper is intentionally kept available, but it is not the canonical
    scheduler input path for the current demo scheduler.
    """

    from app.generate_day import EngineInputs
    from app.infra.db_loader import load_people, load_station_order

    shifts_list = load_shifts()
    rules = load_rules()
    calendar = load_calendar()
    people = _normalize_people_station_skills(load_people(tenant_name))
    station_order = load_station_order(tenant_name)
    return EngineInputs(
        shifts_list=shifts_list,
        rules=rules,
        calendar=calendar,
        people=people,
        station_order=station_order,
    )


def build_inputs_from_json() -> "EngineInputs":
    """Build the canonical demo scheduler engine inputs from ``data/*.json``."""

    from app.generate_day import EngineInputs

    shifts_list = load_shifts()
    rules = load_rules()
    calendar = load_calendar()
    workers = load_workers()

    raw_people = workers.get("people") or []
    people = _normalize_people_station_skills([p for p in raw_people if isinstance(p, dict)])

    def _person_key(p: dict) -> tuple:
        name = p.get("name")
        return (0, str(name).strip().lower()) if name else (1, "")

    people = sorted(people, key=_person_key)

    # Station ordering remains derived from the demo JSON rules until a real
    # scheduler-input migration happens.
    stations = rules.get("stations") or {}
    station_order = sorted(_normalize_station_key(k) for k in stations.keys() if _normalize_station_key(k))

    return EngineInputs(
        shifts_list=shifts_list,
        rules=rules,
        calendar=calendar,
        people=people,
        station_order=station_order,
    )
