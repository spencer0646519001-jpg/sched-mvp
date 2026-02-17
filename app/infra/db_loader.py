from __future__ import annotations

from typing import List


def load_people(tenant_name: str) -> List[dict]:
    from app.db_loaders import load_people_from_db

    return load_people_from_db(tenant_name)


def load_station_order(tenant_name: str) -> List[str]:
    from app.db_loaders import load_station_order_from_db

    return load_station_order_from_db(tenant_name)
