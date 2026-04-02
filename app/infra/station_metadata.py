from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.domain.normalize import canonical_station


@dataclass(frozen=True)
class StationMetadataRecord:
    code: str
    display_name: str
    is_active: bool
    sort_order: int


@dataclass(frozen=True)
class StationMetadataOverlay:
    ordered_codes: list[str]
    by_code: dict[str, StationMetadataRecord]
    lookup: dict[str, str]
    labels: dict[str, str]


def _normalize_station_code_list(raw_codes: object) -> list[str]:
    ordered_codes: list[str] = []
    seen: set[str] = set()
    for raw_code in raw_codes or []:
        code = canonical_station(str(raw_code or ""))
        if not code or code in seen:
            continue
        ordered_codes.append(code)
        seen.add(code)
    return ordered_codes


def _normalize_station_lookup_key(raw: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(raw or "")).strip().lower()


def _coerce_sort_order(raw: Any, *, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def load_station_metadata_rows(tenant_name: str) -> list[dict] | None:
    try:
        from core.models import Station, Tenant

        tenant = Tenant.objects.get(name=tenant_name)
    except Exception:
        return None

    return list(
        Station.objects
        .filter(tenant=tenant)
        .order_by("sort_order", "code")
        .values("code", "display_name", "is_active", "sort_order")
    )


def build_station_metadata_overlay(
    *,
    base_station_codes: list[str],
    db_station_rows: list[dict] | None,
) -> StationMetadataOverlay:
    ordered_codes = _normalize_station_code_list(base_station_codes)

    by_code: dict[str, StationMetadataRecord] = {
        code: StationMetadataRecord(
            code=code,
            display_name=code,
            is_active=True,
            sort_order=index,
        )
        for index, code in enumerate(ordered_codes)
    }

    db_by_code: dict[str, dict] = {}
    for row in db_station_rows or []:
        code = canonical_station(str((row or {}).get("code") or ""))
        if code:
            db_by_code[code] = dict(row)

    for index, code in enumerate(ordered_codes):
        row = db_by_code.get(code)
        if row is None:
            continue
        display_name = str(row.get("display_name") or "").strip() or code
        by_code[code] = StationMetadataRecord(
            code=code,
            display_name=display_name,
            is_active=bool(row.get("is_active", True)),
            sort_order=_coerce_sort_order(row.get("sort_order"), fallback=index),
        )

    lookup: dict[str, str] = {}
    labels: dict[str, str] = {}
    for code in ordered_codes:
        record = by_code[code]
        labels[code] = record.display_name or code

        code_key = _normalize_station_lookup_key(code)
        if code_key:
            lookup[code_key] = code

        label_key = _normalize_station_lookup_key(record.display_name)
        if label_key:
            lookup[label_key] = code

    return StationMetadataOverlay(
        ordered_codes=ordered_codes,
        by_code=by_code,
        lookup=lookup,
        labels=labels,
    )


def load_station_metadata_overlay(
    *,
    tenant_name: str,
    base_station_codes: list[str],
) -> StationMetadataOverlay:
    return build_station_metadata_overlay(
        base_station_codes=base_station_codes,
        db_station_rows=load_station_metadata_rows(tenant_name),
    )


def serialize_station_metadata(
    overlay: StationMetadataOverlay | None,
    *,
    station_codes: list[str] | None = None,
) -> list[dict[str, object]]:
    if overlay is None:
        return []

    if station_codes is None:
        ordered_codes = list(overlay.ordered_codes)
    else:
        ordered_codes = _normalize_station_code_list(station_codes)

    serialized: list[dict[str, object]] = []
    seen: set[str] = set()
    for code in ordered_codes:
        if code in seen:
            continue
        seen.add(code)
        record = overlay.by_code.get(code)
        if record is None:
            continue
        serialized.append(
            {
                "code": record.code,
                "display_name": record.display_name,
                "is_active": record.is_active,
                "sort_order": record.sort_order,
            }
        )
    return serialized
