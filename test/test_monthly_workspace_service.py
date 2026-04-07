import csv
import io
from types import SimpleNamespace

from core.monthly_workspace_service import (
    MonthlyPreviewHooks,
    MonthlyWorkspaceHooks,
    build_monthly_export_csv,
    build_monthly_preview,
    refine_monthly_workspace,
)


def _unexpected_hook(*_args, **_kwargs):
    raise AssertionError("unexpected hook call")


def _workspace_hooks(**overrides):
    defaults = {
        "build_monthly_preview": _unexpected_hook,
        "is_valid_monthly_people_grid": lambda _grid: True,
        "parse_refine_text": _unexpected_hook,
        "parse_refine_text_with_llm_fallback": _unexpected_hook,
        "localize_parse_errors": lambda errors, _language: errors,
        "build_refine_detail": lambda errors, **_kwargs: "; ".join(item.get("message", "") for item in errors),
        "refine_parse_error": lambda line, code, message: {"line": line, "code": code, "message": message},
        "refine_error_message": lambda _language, code: code,
        "apply_refine_operations": _unexpected_hook,
        "annotate_refine_diff_station_metadata": lambda diff, **_kwargs: diff,
        "build_weekly_rest_warnings_from_people_grid": lambda _people_grid: [],
    }
    defaults.update(overrides)
    return MonthlyWorkspaceHooks(**defaults)


def test_build_monthly_preview_sets_language_before_grid_conversion():
    observed = {}
    engine_inputs = object()
    scheduling_inputs = SimpleNamespace(
        start_date="2025-11-01",
        leave_by_date={"2025-11-05": ["Spencer"]},
        engine_inputs=engine_inputs,
        language="en",
    )

    def _generate_month_state(start_date, leave_by_date, engine_inputs=None):
        observed["start_date"] = start_date
        observed["leave_by_date"] = leave_by_date
        observed["engine_inputs"] = engine_inputs
        return {"plan": {}}

    def _plan_to_people_grid(month_state, received_inputs):
        assert received_inputs is scheduling_inputs
        assert month_state["language"] == "en"
        return {"ok": True}

    result = build_monthly_preview(
        scheduling_inputs,
        hooks=MonthlyPreviewHooks(
            generate_month_state_with_leave_requests=_generate_month_state,
            plan_to_people_grid=_plan_to_people_grid,
        ),
    )

    assert result == {"ok": True}
    assert observed == {
        "start_date": "2025-11-01",
        "leave_by_date": {"2025-11-05": ["Spencer"]},
        "engine_inputs": engine_inputs,
    }


def test_build_monthly_export_csv_prefers_valid_working_people_grid():
    date_str = "2025-11-05"
    csv_text = build_monthly_export_csv(
        {
            "working_people_grid": {
                "year_month": "2025-11",
                "dates": [date_str],
                "rows": [
                    {
                        "name": "Spencer",
                        "role": "staff",
                        "cells": [{"code": "OFF", "note": "manual_refine:OFF"}],
                    }
                ],
            }
        },
        object(),
        hooks=_workspace_hooks(build_monthly_preview=_unexpected_hook),
    )

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows == [["name", "role", date_str], ["Spencer", "staff", "OFF"]]


def test_refine_monthly_workspace_preserves_success_payload_shape():
    preview_people_grid = {
        "year_month": "2025-11",
        "dates": ["2025-11-05"],
        "rows": [],
    }
    refined_people_grid = {
        "year_month": "2025-11",
        "dates": ["2025-11-05"],
        "rows": [{"name": "Spencer", "role": "staff", "cells": [{"code": "OFF", "note": ""}]}],
    }
    scheduling_inputs = SimpleNamespace(station_metadata=object(), shift_metadata=object())

    result = refine_monthly_workspace(
        scheduling_inputs=scheduling_inputs,
        year_month="2025-11",
        start_date="2025-11-01",
        language="en",
        refine_text="Spencer 2025-11-05 to OFF",
        hooks=_workspace_hooks(
            build_monthly_preview=lambda _inputs: {
                "people_grid": preview_people_grid,
                "warnings": ["BASE_WARNING"],
                "shift_metadata": [{"code": "OFF"}],
                "station_metadata": [{"code": "gateau"}],
            },
            parse_refine_text=lambda *_args, **_kwargs: ([{"op": "set_off"}], ["PARSE_WARNING"], []),
            apply_refine_operations=lambda _grid, _ops: (
                refined_people_grid,
                [{"action": "set_off", "date": "2025-11-05", "person": "Spencer"}],
                ["REFINE_WARNING"],
            ),
            build_weekly_rest_warnings_from_people_grid=lambda _people_grid: [{"type": "weekly_rest"}],
        ),
    )

    assert result.status_code == 200
    assert result.payload == {
        "ok": True,
        "diff": [{"action": "set_off", "date": "2025-11-05", "person": "Spencer"}],
        "preview_people_grid": refined_people_grid,
        "warnings": ["BASE_WARNING", "PARSE_WARNING", "REFINE_WARNING"],
        "parse_errors": [],
        "weekly_rest_warnings": [{"type": "weekly_rest"}],
        "explain": {"parser": "rule_based_v2", "ops_count": 1, "fallback_used": False},
        "shift_metadata": [{"code": "OFF"}],
        "station_metadata": [{"code": "gateau"}],
    }
