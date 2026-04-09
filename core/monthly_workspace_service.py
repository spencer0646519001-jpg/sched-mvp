"""Request-scoped monthly workspace orchestration.

This module intentionally stays free of Django imports and does not import
``core.api_views_monthly``. The view module passes hooks for the lower-level
helpers that still live there during this first extraction step.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MonthlyPreviewHooks:
    generate_month_state_with_leave_requests: Callable[..., dict]
    plan_to_people_grid: Callable[[dict, Any], dict]


@dataclass(frozen=True)
class MonthlyWorkspaceHooks:
    build_monthly_preview: Callable[[Any], dict]
    is_valid_monthly_people_grid: Callable[[Any], bool]
    parse_refine_text: Callable[..., tuple[list[dict], list[str], list[dict]]]
    parse_refine_text_with_llm_fallback: Callable[..., tuple[list[dict], list[str], list[dict], dict]]
    localize_parse_errors: Callable[[list[dict], str], list[dict]]
    build_refine_detail: Callable[..., str]
    refine_parse_error: Callable[[str, str, str], dict]
    refine_error_message: Callable[[str, str], str]
    apply_refine_operations: Callable[[dict, list[dict]], tuple[dict, list[dict], list[str]]]
    annotate_refine_diff_station_metadata: Callable[..., list[dict]]
    build_weekly_rest_warnings_from_people_grid: Callable[[dict], list[dict]]


@dataclass(frozen=True)
class MonthlyRefineResult:
    payload: dict
    status_code: int


def build_monthly_working_state(*, people_grid, weekly_rest_warnings=None, warnings=None) -> dict | None:
    if not isinstance(people_grid, dict):
        return None
    return {
        "people_grid": people_grid,
        "weekly_rest_warnings": list(weekly_rest_warnings or []),
        "warnings": list(warnings or []),
    }


def is_valid_monthly_working_state(
    working_state: Any,
    *,
    hooks: MonthlyWorkspaceHooks,
) -> bool:
    if not isinstance(working_state, dict):
        return False

    if not hooks.is_valid_monthly_people_grid(working_state.get("people_grid")):
        return False

    warnings = working_state.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        return False

    weekly_rest_warnings = working_state.get("weekly_rest_warnings", [])
    if not isinstance(weekly_rest_warnings, list):
        return False
    if any(not isinstance(item, dict) for item in weekly_rest_warnings):
        return False

    return True


def build_monthly_preview(scheduling_inputs: Any, *, hooks: MonthlyPreviewHooks) -> dict:
    """Build the canonical monthly preview from the shared scheduling input contract."""
    month_state = hooks.generate_month_state_with_leave_requests(
        scheduling_inputs.start_date,
        scheduling_inputs.leave_by_date,
        engine_inputs=scheduling_inputs.engine_inputs,
    )
    month_state["language"] = scheduling_inputs.language
    return hooks.plan_to_people_grid(month_state, scheduling_inputs)


def build_monthly_preview_payload(scheduling_inputs: Any, *, hooks: MonthlyWorkspaceHooks) -> dict:
    return hooks.build_monthly_preview(scheduling_inputs)


def resolve_monthly_export_people_grid(
    payload: dict,
    scheduling_inputs: Any,
    *,
    hooks: MonthlyWorkspaceHooks,
) -> dict:
    working_state = payload.get("working_state")
    if working_state is not None:
        if not is_valid_monthly_working_state(working_state, hooks=hooks):
            raise ValueError("Invalid 'working_state' payload.")
        return dict(working_state.get("people_grid") or {})

    # The monthly demo UI can carry a newer request-scoped working grid after
    # refine/apply. Export should consume that same effective state when present,
    # while still falling back to rebuilding the baseline preview for older callers.
    working_people_grid = payload.get("working_people_grid")
    if working_people_grid is not None:
        if not hooks.is_valid_monthly_people_grid(working_people_grid):
            raise ValueError("Invalid 'working_people_grid' payload.")
        return working_people_grid

    preview = hooks.build_monthly_preview(scheduling_inputs)
    return preview.get("people_grid", {})


def build_monthly_export_csv(
    payload: dict,
    scheduling_inputs: Any,
    *,
    hooks: MonthlyWorkspaceHooks,
) -> str:
    people_grid = resolve_monthly_export_people_grid(payload, scheduling_inputs, hooks=hooks)
    dates = people_grid.get("dates", [])
    rows = people_grid.get("rows", [])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "role", *dates])
    for row in rows:
        cells = row.get("cells", [])
        writer.writerow(
            [row.get("name", ""), row.get("role", "")]
            + [((cell or {}).get("code", "")) for cell in cells]
        )

    return buf.getvalue()


def refine_monthly_workspace(
    *,
    scheduling_inputs: Any,
    year_month: str,
    start_date: str,
    language: str,
    refine_text: str,
    working_state: dict | None = None,
    hooks: MonthlyWorkspaceHooks,
) -> MonthlyRefineResult:
    # Current monthly demo path: build a request-scoped preview from JSON-backed
    # engine inputs plus request leave overrides. No monthly plan is persisted here.
    preview = hooks.build_monthly_preview(scheduling_inputs)
    if working_state is not None and not is_valid_monthly_working_state(working_state, hooks=hooks):
        raise ValueError("Invalid 'working_state' payload.")

    if working_state is not None:
        people_grid = dict(working_state.get("people_grid") or {})
        warnings = list(working_state.get("warnings", []) or [])
    else:
        people_grid = preview.get("people_grid", {})
        warnings = list(preview.get("warnings", []) or [])
    station_metadata = getattr(scheduling_inputs, "station_metadata", None)
    shift_metadata = getattr(scheduling_inputs, "shift_metadata", None)

    ops, parse_warnings, parse_errors = hooks.parse_refine_text(
        refine_text,
        start_date=start_date,
        people_grid=people_grid,
        station_metadata=station_metadata,
        shift_metadata=shift_metadata,
    )
    parser_name = "rule_based_v2"
    fallback_used = False

    if parse_errors and not ops:
        llm_ops, llm_warnings, llm_parse_errors, llm_explain = hooks.parse_refine_text_with_llm_fallback(
            refine_text=refine_text,
            year_month=year_month,
            start_date=start_date,
            language=language,
            people_grid=people_grid,
            station_metadata=station_metadata,
            shift_metadata=shift_metadata,
        )
        parse_warnings.extend(llm_warnings)

        if llm_ops and not llm_parse_errors:
            ops = llm_ops
            parse_errors = []
            parser_name = str(llm_explain.get("parser") or "llm_fallback_v1")
            fallback_used = True
        else:
            all_parse_errors = list(parse_errors) + list(llm_parse_errors)
            localized_errors = hooks.localize_parse_errors(all_parse_errors, language)
            detail = hooks.build_refine_detail(localized_errors, language=language)
            if not localized_errors:
                localized_errors = [
                    hooks.refine_parse_error(
                        refine_text,
                        "llm_unknown",
                        hooks.refine_error_message(language, "llm_unknown"),
                    )
                ]
                detail = hooks.build_refine_detail(localized_errors, language=language)
            return MonthlyRefineResult(
                payload={
                    "ok": False,
                    "detail": detail,
                    "parse_errors": localized_errors,
                },
                status_code=400,
            )

    localized_parse_errors = hooks.localize_parse_errors(parse_errors, language)

    if parse_errors and not ops:
        detail = hooks.build_refine_detail(localized_parse_errors, language=language)
        return MonthlyRefineResult(
            payload={
                "ok": False,
                "detail": detail,
                "parse_errors": localized_parse_errors,
            },
            status_code=400,
        )

    preview_people_grid, diff, refine_warnings = hooks.apply_refine_operations(people_grid, ops)
    diff = hooks.annotate_refine_diff_station_metadata(
        diff,
        station_metadata=station_metadata,
    )

    warnings.extend(parse_warnings)
    warnings.extend(refine_warnings)
    weekly_rest_warnings = hooks.build_weekly_rest_warnings_from_people_grid(preview_people_grid)

    return MonthlyRefineResult(
        payload={
            "ok": True,
            "diff": diff,
            "preview_people_grid": preview_people_grid,
            "warnings": warnings,
            "parse_errors": localized_parse_errors,
            "weekly_rest_warnings": weekly_rest_warnings,
            "explain": {"parser": parser_name, "ops_count": len(ops), "fallback_used": fallback_used},
            "shift_metadata": preview.get("shift_metadata", []),
            "station_metadata": preview.get("station_metadata", []),
        },
        status_code=200,
    )
