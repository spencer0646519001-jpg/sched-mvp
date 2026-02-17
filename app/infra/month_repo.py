from __future__ import annotations

from typing import Dict, List

from core.models import EmployeeStationSkill, Station, Tenant


def build_station_map(tenant_name: str) -> Dict[str, List[str]]:
    tenant = Tenant.objects.get(name=tenant_name)

    stations = (
        Station.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("sort_order", "code")
    )

    station_map: Dict[str, List[str]] = {}

    for st in stations:
        skills = (
            EmployeeStationSkill.objects
            .filter(tenant=tenant, station=st, employee__is_assignable=True, employee__is_active=True)
            .order_by("-level")
        )
        station_map[st.code] = [s.employee.name for s in skills]

    return station_map
