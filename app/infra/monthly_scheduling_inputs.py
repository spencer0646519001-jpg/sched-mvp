from __future__ import annotations

from dataclasses import dataclass
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


def _load_role_by_name_from_db(tenant_name: str) -> dict[str, str]:
    # Keep the monthly demo read path compatible while only a subset is DB-backed.
    try:
        people = load_people(tenant_name)
    except Exception:
        return {}

    return {
        person.get("name"): person.get("role", "")
        for person in people
        if isinstance(person, dict) and person.get("name")
    }


def _build_worker_ordering(tenant_name: str) -> tuple[list[str], dict[str, str]]:
    ordered_names, role_by_name = _load_worker_ordering_from_json()
    db_role_by_name = _load_role_by_name_from_db(tenant_name)

    for name in ordered_names:
        if name in db_role_by_name:
            role_by_name[name] = db_role_by_name[name]

    return ordered_names, role_by_name


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
    - request leave overrides are applied at the monthly API boundary
    """

    ordered_names, role_by_name = _build_worker_ordering(tenant_name)
    return MonthlySchedulingInputs(
        start_date=start_date,
        language=language,
        leave_requests={name: list(dates) for name, dates in leave_requests.items()},
        leave_by_date={date_str: list(names) for date_str, names in leave_by_date.items()},
        engine_inputs=build_inputs_from_json(),
        ordered_names=ordered_names,
        role_by_name=role_by_name,
    )
