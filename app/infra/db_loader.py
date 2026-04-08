"""DB-backed read helpers for overlays and non-canonical helper paths.

These helpers are real and useful, but they are not the canonical demo
scheduler input source of truth today.
"""

from __future__ import annotations

from typing import List


def load_people(tenant_name: str) -> List[dict]:
    """Load DB-backed people rows for overlays or non-canonical helper paths."""

    from app.db_loaders import load_people_from_db

    return load_people_from_db(tenant_name)


def load_station_order(tenant_name: str) -> List[str]:
    """Load DB-backed station ordering for overlays or non-canonical helpers."""

    from app.db_loaders import load_station_order_from_db

    return load_station_order_from_db(tenant_name)
