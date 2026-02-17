from __future__ import annotations

from typing import Dict, List


def load_people_from_db(tenant_name: str) -> List[Dict]:
    """
    DB -> people(list[dict]) adapter
    目標：輸出格式貼近原本 workers.json 的 people
    """
    from core.models import Tenant, Employee, EmployeeStationSkill

    tenant = Tenant.objects.get(name=tenant_name)

    employees = (
        Employee.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("name")
    )

    # 一次撈出 skills，避免 N+1 queries
    skills = (
        EmployeeStationSkill.objects
        .filter(tenant=tenant, employee__in=employees)
        .select_related("employee", "station")
    )

    skill_map: Dict[str, List[str]] = {}
    for s in skills:
        skill_map.setdefault(s.employee.name, []).append(s.station.code)

    people: List[Dict] = []
    for e in employees:
        people.append(
            {
                "name": e.name,
                "role": getattr(e, "role", "staff"),
                "station_skills": skill_map.get(e.name, []),
            }
        )

    return people


def load_station_order_from_db(tenant_name: str) -> List[str]:
    from core.models import Tenant, Station

    tenant = Tenant.objects.get(name=tenant_name)
    return list(
        Station.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("sort_order", "code")
        .values_list("code", flat=True)
    )
