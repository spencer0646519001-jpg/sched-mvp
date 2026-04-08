"""Monthly refine apply and diff helpers."""

from __future__ import annotations

import json

from app.domain.normalize import canonical_station
from core.monthly_refine_parser import (
    _extract_station_tokens_from_note,
    _normalize_person_lookup_key,
    _normalize_station_lookup_key,
)


def _station_label(station: str, station_metadata) -> str:
    code = canonical_station(str(station or ""))
    if not code:
        return ""
    if station_metadata is not None:
        label = (getattr(station_metadata, "labels", {}) or {}).get(code)
        if label:
            return str(label)
    return code


def _annotate_refine_diff_station_metadata(diff: list[dict], *, station_metadata) -> list[dict]:
    if not isinstance(diff, list):
        return []

    annotated: list[dict] = []
    for item in diff:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        station = copied.get("station")
        if station:
            copied["station_label"] = _station_label(str(station), station_metadata)
        annotated.append(copied)
    return annotated


def _people_grid_to_lookup(people_grid: dict) -> tuple[dict, dict, dict]:
    date_to_index = {d: i for i, d in enumerate((people_grid.get("dates") or []))}
    row_by_name: dict[str, dict] = {}
    row_by_name_folded: dict[str, dict] = {}
    for row in people_grid.get("rows", []) or []:
        name = row.get("name")
        if not isinstance(name, str) or not name:
            continue
        row_by_name[name] = row
        row_by_name_folded[_normalize_person_lookup_key(name)] = row
    return date_to_index, row_by_name, row_by_name_folded


def _ensure_refine_row(people_grid: dict, person: str) -> dict:
    for row in people_grid.get("rows", []) or []:
        if row.get("name") == person:
            return row
    dates = people_grid.get("dates") or []
    new_row = {
        "name": person,
        "role": "unknown",
        "cells": [{"code": "", "note": ""} for _ in dates],
    }
    people_grid.setdefault("rows", []).append(new_row)
    return new_row


def _resolve_person_row(people_grid: dict, person: str) -> tuple[str, dict]:
    date_to_index, row_by_name, row_by_name_folded = _people_grid_to_lookup(people_grid)
    _ = date_to_index
    if person in row_by_name:
        return person, row_by_name[person]
    lookup_key = _normalize_person_lookup_key(person)
    if lookup_key in row_by_name_folded:
        row = row_by_name_folded[lookup_key]
        return row.get("name") or person, row
    row = _ensure_refine_row(people_grid, person)
    return person, row


def _find_station_holder(people_grid: dict, date_str: str, station: str) -> tuple[str | None, dict | None]:
    date_to_index, _, _ = _people_grid_to_lookup(people_grid)
    idx = date_to_index.get(date_str)
    if idx is None:
        return None, None
    station_norm = _normalize_station_lookup_key(station)
    for row in people_grid.get("rows", []) or []:
        cells = row.get("cells") or []
        if idx >= len(cells):
            continue
        cell = cells[idx] or {}
        note = str(cell.get("note", "") or "")
        code = str(cell.get("code", "") or "")
        station_tokens = _extract_station_tokens_from_note(note)
        token_keys = {_normalize_station_lookup_key(tok) for tok in station_tokens}
        if station_norm and station_norm in token_keys and code:
            return row.get("name"), cell
    return None, None


def _apply_refine_operations(base_people_grid: dict, operations: list[dict]) -> tuple[dict, list[dict], list[str]]:
    preview_people_grid = json.loads(json.dumps(base_people_grid))
    diffs: list[dict] = []
    warnings: list[str] = []
    date_to_index, _, _ = _people_grid_to_lookup(preview_people_grid)

    for op in operations:
        op_type = op.get("type")
        if op_type == "set_shift":
            person = op.get("person")
            date_str = op.get("date")
            shift_code = op.get("shift")
            if not person or date_str not in date_to_index or not shift_code:
                warnings.append(f"REFINE_SKIPPED:set_shift:{person}:{date_str}:{shift_code}")
                continue
            resolved_name, row = _resolve_person_row(preview_people_grid, person)
            idx = date_to_index[date_str]
            cell = ((row.get("cells") or [])[idx]) or {}
            from_code = str(cell.get("code", "") or "")
            from_note = str(cell.get("note", "") or "")
            to_note = from_note
            row["cells"][idx] = {"code": shift_code, "note": to_note}
            diffs.append(
                {
                    "action": "set_shift",
                    "date": date_str,
                    "person": resolved_name,
                    "station": None,
                    "from": {"code": from_code, "note": from_note},
                    "to": {"code": shift_code, "note": to_note},
                }
            )
            continue

        if op_type == "set_off":
            person = op.get("person")
            date_str = op.get("date")
            if not person or date_str not in date_to_index:
                warnings.append(f"REFINE_SKIPPED:set_off:{person}:{date_str}")
                continue
            resolved_name, row = _resolve_person_row(preview_people_grid, person)
            idx = date_to_index[date_str]
            cell = ((row.get("cells") or [])[idx]) or {}
            from_code = str(cell.get("code", "") or "")
            from_note = str(cell.get("note", "") or "")
            to_note = "manual_refine:OFF"
            row["cells"][idx] = {"code": "OFF", "note": to_note}
            diffs.append(
                {
                    "action": "set_off",
                    "date": date_str,
                    "person": resolved_name,
                    "station": None,
                    "from": {"code": from_code, "note": from_note},
                    "to": {"code": "OFF", "note": to_note},
                }
            )
            continue

        if op_type == "replace_station":
            date_str = op.get("date")
            station = op.get("station")
            new_person = op.get("new_person")
            if not date_str or date_str not in date_to_index or not station or not new_person:
                warnings.append(f"REFINE_SKIPPED:replace_station:{date_str}:{station}:{new_person}")
                continue

            idx = date_to_index[date_str]
            old_person, old_cell = _find_station_holder(preview_people_grid, date_str, station)
            resolved_new_name, new_row = _resolve_person_row(preview_people_grid, new_person)
            new_cell = ((new_row.get("cells") or [])[idx]) or {}

            inherited_code = str((old_cell or {}).get("code", "") or "") or "A"
            to_note = f"manual_refine:{station}"
            from_new_code = str(new_cell.get("code", "") or "")
            from_new_note = str(new_cell.get("note", "") or "")
            new_row["cells"][idx] = {"code": inherited_code, "note": to_note}

            if old_person:
                resolved_old_name, old_row = _resolve_person_row(preview_people_grid, old_person)
                old_row["cells"][idx] = {"code": "", "note": f"manual_refine:removed_from:{station}"}
                diffs.append(
                    {
                        "action": "replace_station_old",
                        "date": date_str,
                        "person": resolved_old_name,
                        "station": station,
                        "from": {
                            "code": str((old_cell or {}).get("code", "") or ""),
                            "note": str((old_cell or {}).get("note", "") or ""),
                        },
                        "to": {"code": "", "note": f"manual_refine:removed_from:{station}"},
                    }
                )
            else:
                warnings.append(f"REFINE_NO_OLD_HOLDER:{date_str}:{station}")

            diffs.append(
                {
                    "action": "replace_station_new",
                    "date": date_str,
                    "person": resolved_new_name,
                    "station": station,
                    "from": {"code": from_new_code, "note": from_new_note},
                    "to": {"code": inherited_code, "note": to_note},
                }
            )
            continue

        if op_type == "add_station":
            date_str = op.get("date")
            station = op.get("station")
            person = op.get("person")
            if not date_str or date_str not in date_to_index or not station:
                warnings.append(f"REFINE_SKIPPED:add_station:{date_str}:{station}")
                continue

            idx = date_to_index[date_str]
            target_person = person
            if not target_person:
                for row in preview_people_grid.get("rows", []) or []:
                    cell = ((row.get("cells") or [])[idx]) or {}
                    if not str(cell.get("code", "") or ""):
                        target_person = row.get("name")
                        break
            if not target_person:
                warnings.append(f"REFINE_NO_FREE_PERSON:{date_str}:{station}")
                continue

            resolved_name, target_row = _resolve_person_row(preview_people_grid, target_person)
            target_cell = ((target_row.get("cells") or [])[idx]) or {}
            from_code = str(target_cell.get("code", "") or "")
            from_note = str(target_cell.get("note", "") or "")
            if from_code:
                warnings.append(f"REFINE_OVERWRITE:{resolved_name}:{date_str}")
            target_row["cells"][idx] = {"code": "A", "note": f"manual_refine:{station}"}
            diffs.append(
                {
                    "action": "add_station",
                    "date": date_str,
                    "person": resolved_name,
                    "station": station,
                    "from": {"code": from_code, "note": from_note},
                    "to": {"code": "A", "note": f"manual_refine:{station}"},
                }
            )
            continue

        warnings.append(f"REFINE_UNKNOWN_OP:{op_type}")

    return preview_people_grid, diffs, warnings
