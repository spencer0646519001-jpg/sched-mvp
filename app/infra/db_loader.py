from __future__ import annotations

from typing import List


def load_people(tenant_name: str) -> List[dict]:
    from app.db_loaders import load_people_from_db

    return load_people_from_db(tenant_name)


def load_station_order(tenant_name: str) -> List[str]:
    from core.models import Tenant, Station

    tenant = Tenant.objects.get(name=tenant_name)
    return list(
        Station.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("sort_order", "code")
        .values_list("code", flat=True)
    )
