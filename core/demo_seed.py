from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from app.domain.normalize import canonical_station
from app.infra.engine_input_resolver import (
    DEMO_TENANT_NAME,
    resolve_engine_inputs_for_tenant,
)
from core.models import Employee, Station, Tenant


@dataclass(frozen=True)
class DemoSeedSummary:
    tenant_created: bool
    stations_created: int
    employees_created: int


@dataclass(frozen=True)
class DemoSeedSpec:
    station_rows: list[dict[str, object]]
    employee_rows: list[dict[str, object]]


def _build_demo_seed_spec() -> DemoSeedSpec:
    inputs = resolve_engine_inputs_for_tenant(DEMO_TENANT_NAME)

    station_rows: list[dict[str, object]] = []
    seen_station_codes: set[str] = set()
    for raw_code in getattr(inputs, "station_order", []) or []:
        code = canonical_station(str(raw_code or ""))
        if not code or code in seen_station_codes:
            continue

        seen_station_codes.add(code)
        station_rows.append(
            {
                "code": code,
                "display_name": code,
                "sort_order": len(station_rows) * 10,
            }
        )

    employee_rows: list[dict[str, object]] = []
    seen_employee_names: set[str] = set()
    for person in getattr(inputs, "people", []) or []:
        if not isinstance(person, dict):
            continue

        name = str(person.get("name") or "").strip()
        if not name or name in seen_employee_names:
            continue

        seen_employee_names.add(name)
        role = str(person.get("role") or "").strip().lower()
        employee_rows.append(
            {
                "name": name,
                "role": "chef" if role == "chef" else "staff",
                "is_assignable": not bool(person.get("headcount_only")),
            }
        )

    return DemoSeedSpec(
        station_rows=station_rows,
        employee_rows=employee_rows,
    )


@transaction.atomic
def ensure_demo_seed_data() -> DemoSeedSummary:
    spec = _build_demo_seed_spec()
    tenant, tenant_created = Tenant.objects.get_or_create(name=DEMO_TENANT_NAME)

    stations_created = 0
    for row in spec.station_rows:
        _, created = Station.objects.get_or_create(
            tenant=tenant,
            code=str(row["code"]),
            defaults={
                "display_name": str(row["display_name"]),
                "sort_order": int(row["sort_order"]),
                "is_active": True,
            },
        )
        if created:
            stations_created += 1

    employees_created = 0
    for row in spec.employee_rows:
        _, created = Employee.objects.get_or_create(
            tenant=tenant,
            name=str(row["name"]),
            defaults={
                "role": str(row["role"]),
                "is_assignable": bool(row["is_assignable"]),
                "is_active": True,
            },
        )
        if created:
            employees_created += 1

    return DemoSeedSummary(
        tenant_created=tenant_created,
        stations_created=stations_created,
        employees_created=employees_created,
    )
