from __future__ import annotations

from dataclasses import dataclass, is_dataclass, replace
from typing import TYPE_CHECKING

from app.infra.db_loader import load_people
from app.infra.engine_inputs import build_inputs_from_json
from app.infra.json_loader import load_workers

if TYPE_CHECKING:
    from app.generate_day import EngineInputs


@dataclass(frozen=True)
class MonthlySchedulingInputs:
    start_date: str
    language: str
    leave_requests: dict[str, list[str]]
    leave_by_date: dict[str, list[str]]
    engine_inputs: "EngineInputs"
    ordered_names: list[str]
    role_by_name: dict[str, str]


MONTHLY_DEMO_TENANT_NAME = "demo_kitchen"


def _normalize_station_skill_codes(raw_codes: object) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_code in raw_codes or []:
        code = str(raw_code or "").strip().lower()
        if not code or code in seen:
            continue
        normalized.append(code)
        seen.add(code)
    return normalized


def _load_worker_ordering_from_json() -> tuple[list[str], dict[str, str]]:
    workers = load_workers().get("people", [])
    role_by_name = {
        person.get("name"): person.get("role", "")
        for person in workers
        if isinstance(person, dict) and person.get("name")
    }
    ordered_names = [
        person.get("name")
        for person in workers
        if isinstance(person, dict) and person.get("name")
    ]
    return ordered_names, role_by_name


def _load_db_people_overlay(tenant_name: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    # Keep the monthly demo read path compatible while only a subset is DB-backed.
    try:
        people = load_people(tenant_name)
    except Exception:
        return {}, {}

    role_by_name = {
        person.get("name"): person.get("role", "")
        for person in people
        if isinstance(person, dict) and person.get("name")
    }
    station_skills_by_name = {
        person.get("name"): normalized_skills
        for person in people
        if isinstance(person, dict)
        and person.get("name")
        and (normalized_skills := _normalize_station_skill_codes(person.get("station_skills") or []))
    }
    return role_by_name, station_skills_by_name


def _build_worker_ordering(db_role_by_name: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    ordered_names, role_by_name = _load_worker_ordering_from_json()

    for name in ordered_names:
        if name in db_role_by_name:
            role_by_name[name] = db_role_by_name[name]

    return ordered_names, role_by_name


def _overlay_engine_input_station_skills(
    engine_inputs: "EngineInputs",
    db_station_skills_by_name: dict[str, list[str]],
) -> "EngineInputs":
    if not db_station_skills_by_name or not is_dataclass(engine_inputs):
        return engine_inputs

    base_people = getattr(engine_inputs, "people", None)
    if not isinstance(base_people, list):
        return engine_inputs

    overlay_people: list[dict] = []
    overlay_applied = False

    for person in base_people:
        if not isinstance(person, dict):
            overlay_people.append(person)
            continue

        copied = dict(person)
        name = copied.get("name")
        if name in db_station_skills_by_name:
            copied["station_skills"] = list(db_station_skills_by_name[name])
            overlay_applied = True
        overlay_people.append(copied)

    if not overlay_applied:
        return engine_inputs

    return replace(engine_inputs, people=overlay_people)


def build_monthly_scheduling_inputs(
    *,
    start_date: str,
    language: str,
    leave_requests: dict[str, list[str]],
    leave_by_date: dict[str, list[str]],
    tenant_name: str = MONTHLY_DEMO_TENANT_NAME,
) -> MonthlySchedulingInputs:
    """
    Assemble the canonical request-scoped inputs for the monthly demo flow.

    Current architecture truth:
    - scheduling engine inputs are still JSON-backed
    - monthly people ordering still follows workers.json for compatibility
    - monthly role metadata now prefers DB-backed employee records
    - monthly station capability lookup now prefers DB-backed employee-station skills when present
    - request leave overrides are applied at the monthly API boundary
    """

    db_role_by_name, db_station_skills_by_name = _load_db_people_overlay(tenant_name)
    ordered_names, role_by_name = _build_worker_ordering(db_role_by_name)
    engine_inputs = build_inputs_from_json()
    engine_inputs = _overlay_engine_input_station_skills(engine_inputs, db_station_skills_by_name)
    return MonthlySchedulingInputs(
        start_date=start_date,
        language=language,
        leave_requests={name: list(dates) for name, dates in leave_requests.items()},
        leave_by_date={date_str: list(names) for date_str, names in leave_by_date.items()},
        engine_inputs=engine_inputs,
        ordered_names=ordered_names,
        role_by_name=role_by_name,
    )
