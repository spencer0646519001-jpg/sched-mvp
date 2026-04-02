from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.domain.normalize import canonical_shift


@dataclass(frozen=True)
class ShiftMetadataRecord:
    code: str
    display_name: str
    legend_label: str
    start: str
    end: str
    break_minutes: int | None
    paid_hours: float | None


@dataclass(frozen=True)
class ShiftMetadataOverlay:
    ordered_codes: list[str]
    by_code: dict[str, ShiftMetadataRecord]
    lookup: dict[str, str]
    labels: dict[str, str]


def _normalize_shift_lookup_key(raw: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(raw or "")).strip().lower()


def _coerce_optional_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _coerce_optional_text(raw: Any) -> str:
    return str(raw or "").strip()


def _normalize_base_shift_defs(base_shift_defs: object) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in base_shift_defs or []:
        if not isinstance(item, dict):
            continue
        code = canonical_shift(str(item.get("code") or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(
            {
                "code": code,
                "display_name": _coerce_optional_text(item.get("display_name")) or code,
                "legend_label": _coerce_optional_text(item.get("legend_label")),
                "start": _coerce_optional_text(item.get("start")),
                "end": _coerce_optional_text(item.get("end")),
                "break_minutes": _coerce_optional_int(item.get("break_minutes")),
                "paid_hours": _coerce_optional_float(item.get("paid_hours")),
            }
        )
    return normalized


def load_shift_metadata_rows(tenant_name: str) -> list[dict] | None:
    try:
        from core.models import ShiftDefinition, Tenant

        tenant = Tenant.objects.get(name=tenant_name)
        return list(
            ShiftDefinition.objects
            .filter(tenant=tenant)
            .order_by("code")
            .values("code", "display_name", "legend_label", "paid_hours")
        )
    except Exception:
        return None


def build_shift_metadata_overlay(
    *,
    base_shift_defs: list[dict],
    db_shift_rows: list[dict] | None,
) -> ShiftMetadataOverlay:
    normalized_base_defs = _normalize_base_shift_defs(base_shift_defs)
    ordered_codes = [item["code"] for item in normalized_base_defs]

    by_code: dict[str, ShiftMetadataRecord] = {
        item["code"]: ShiftMetadataRecord(
            code=item["code"],
            display_name=item["display_name"],
            legend_label=item["legend_label"],
            start=item["start"],
            end=item["end"],
            break_minutes=item["break_minutes"],
            paid_hours=item["paid_hours"],
        )
        for item in normalized_base_defs
    }

    db_by_code: dict[str, dict] = {}
    for row in db_shift_rows or []:
        code = canonical_shift(str((row or {}).get("code") or ""))
        if not code:
            continue
        db_by_code[code] = dict(row)

    for item in normalized_base_defs:
        code = item["code"]
        row = db_by_code.get(code)
        if row is None:
            continue

        display_name = _coerce_optional_text(row.get("display_name")) or item["display_name"] or code
        legend_label = _coerce_optional_text(row.get("legend_label"))
        paid_hours = _coerce_optional_float(row.get("paid_hours"))
        if paid_hours is None:
            paid_hours = item["paid_hours"]

        by_code[code] = ShiftMetadataRecord(
            code=code,
            display_name=display_name,
            legend_label=legend_label,
            start=item["start"],
            end=item["end"],
            break_minutes=item["break_minutes"],
            paid_hours=paid_hours,
        )

    lookup: dict[str, str] = {}
    labels: dict[str, str] = {}
    for code in ordered_codes:
        record = by_code[code]
        labels[code] = record.display_name or code

        code_key = _normalize_shift_lookup_key(code)
        if code_key:
            lookup[code_key] = code

        label_key = _normalize_shift_lookup_key(record.display_name)
        if label_key:
            lookup[label_key] = code

    return ShiftMetadataOverlay(
        ordered_codes=ordered_codes,
        by_code=by_code,
        lookup=lookup,
        labels=labels,
    )


def load_shift_metadata_overlay(
    *,
    tenant_name: str,
    base_shift_defs: list[dict],
) -> ShiftMetadataOverlay:
    return build_shift_metadata_overlay(
        base_shift_defs=base_shift_defs,
        db_shift_rows=load_shift_metadata_rows(tenant_name),
    )


def serialize_shift_metadata(
    overlay: ShiftMetadataOverlay | None,
    *,
    shift_codes: list[str] | None = None,
) -> list[dict[str, object]]:
    if overlay is None:
        return []

    if shift_codes is None:
        ordered_codes = list(overlay.ordered_codes)
    else:
        ordered_codes = []
        seen: set[str] = set()
        for raw_code in shift_codes:
            code = canonical_shift(str(raw_code or ""))
            if not code or code in seen:
                continue
            ordered_codes.append(code)
            seen.add(code)

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
                "legend_label": record.legend_label,
                "start": record.start,
                "end": record.end,
                "break_minutes": record.break_minutes,
                "paid_hours": record.paid_hours,
            }
        )
    return serialized
