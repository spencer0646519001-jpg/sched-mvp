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


@dataclass(frozen=True)
class MonthlyRosterMetadata:
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


def _load_db_people(tenant_name: str) -> list[dict] | None:
    # Keep the monthly demo read path compatible while only a subset is DB-backed.
    try:
        return load_people(tenant_name)
    except Exception:
        return None


def _build_db_role_by_name(people: list[dict]) -> dict[str, str]:
    role_by_name = {
        person.get("name"): person.get("role", "")
        for person in people
        if isinstance(person, dict) and person.get("name")
    }
    return role_by_name


def _build_db_station_skills_by_name(people: list[dict]) -> dict[str, list[str]]:
    station_skills_by_name = {
        person.get("name"): normalized_skills
        for person in people
        if isinstance(person, dict)
        and person.get("name")
        and (normalized_skills := _normalize_station_skill_codes(person.get("station_skills") or []))
    }
    return station_skills_by_name


def _ordered_db_names(people: list[dict]) -> list[str]:
    ordered_names: list[str] = []
    seen: set[str] = set()
    for person in people:
        if not isinstance(person, dict):
            continue
        name = person.get("name")
        if not name or name in seen:
            continue
        ordered_names.append(name)
        seen.add(name)
    return ordered_names


def _build_monthly_roster_metadata(
    *,
    json_ordered_names: list[str],
    json_role_by_name: dict[str, str],
    db_people: list[dict] | None,
) -> MonthlyRosterMetadata:
    if db_people is None:
        return MonthlyRosterMetadata(
            ordered_names=list(json_ordered_names),
            role_by_name=dict(json_role_by_name),
        )

    db_ordered_names = _ordered_db_names(db_people)
    db_name_set = set(db_ordered_names)
    json_name_set = set(json_ordered_names)

    ordered_names = [name for name in json_ordered_names if name in db_name_set]
    ordered_names.extend(name for name in db_ordered_names if name not in json_name_set)

    role_by_name = dict(json_role_by_name)
    role_by_name.update(_build_db_role_by_name(db_people))

    return MonthlyRosterMetadata(
        ordered_names=ordered_names,
        role_by_name=role_by_name,
    )


def load_monthly_roster_metadata(
    *,
    tenant_name: str = MONTHLY_DEMO_TENANT_NAME,
) -> MonthlyRosterMetadata:
    db_people = _load_db_people(tenant_name)
    return _load_monthly_roster_metadata_from_sources(db_people)


def _load_monthly_roster_metadata_from_sources(
    db_people: list[dict] | None,
) -> MonthlyRosterMetadata:
    json_ordered_names, json_role_by_name = _load_worker_ordering_from_json()
    return _build_monthly_roster_metadata(
        json_ordered_names=json_ordered_names,
        json_role_by_name=json_role_by_name,
        db_people=db_people,
    )


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
    - monthly roster metadata now prefers DB-backed active Employee records
    - monthly row ordering keeps JSON order where possible for compatibility
    - monthly station capability lookup now prefers DB-backed employee-station skills when present
    - request leave overrides are applied at the monthly API boundary
    """

    db_people = _load_db_people(tenant_name)
    roster_metadata = _load_monthly_roster_metadata_from_sources(db_people)
    db_station_skills_by_name = _build_db_station_skills_by_name(db_people or [])
    engine_inputs = build_inputs_from_json()
    engine_inputs = _overlay_engine_input_station_skills(engine_inputs, db_station_skills_by_name)
    return MonthlySchedulingInputs(
        start_date=start_date,
        language=language,
        leave_requests={name: list(dates) for name, dates in leave_requests.items()},
        leave_by_date={date_str: list(names) for date_str, names in leave_by_date.items()},
        engine_inputs=engine_inputs,
        ordered_names=list(roster_metadata.ordered_names),
        role_by_name=dict(roster_metadata.role_by_name),
    )
