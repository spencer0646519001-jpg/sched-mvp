from __future__ import annotations

from app.infra.db_loader import load_people, load_station_order
from app.infra.json_loader import load_calendar, load_rules, load_shifts, load_workers
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.generate_day import EngineInputs


def build_inputs_from_db(tenant_name: str) -> "EngineInputs":
    from app.generate_day import EngineInputs

    shifts_list = load_shifts()
    rules = load_rules()
    calendar = load_calendar()
    people = load_people(tenant_name)
    station_order = load_station_order(tenant_name)
    return EngineInputs(
        shifts_list=shifts_list,
        rules=rules,
        calendar=calendar,
        people=people,
        station_order=station_order,
    )


def build_inputs_from_json() -> "EngineInputs":
    from app.generate_day import EngineInputs

    shifts_list = load_shifts()
    rules = load_rules()
    calendar = load_calendar()
    workers = load_workers()
    people = workers.get("people") or []
    station_order = [str(k).strip().lower() for k in (rules.get("stations") or {}).keys()]
    return EngineInputs(
        shifts_list=shifts_list,
        rules=rules,
        calendar=calendar,
        people=[p for p in people if isinstance(p, dict)],
        station_order=station_order,
    )
