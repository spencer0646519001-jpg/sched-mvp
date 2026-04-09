"""Reviewer-facing evaluation story for refine and scheduling invariants.

This file is intentionally small. It is not a benchmark harness.
It freezes a handful of offline, reproducible cases that demonstrate:
- the current monthly refine contract
- fallback classification behavior
- working_state precedence
- a couple of supporting scheduling invariants
"""

import json
import os

import django

from app.generate_day import greedy_assign


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def _api_views():
    _django_setup()
    import core.api_views_monthly as api_views

    return api_views


def _daily_assignments_signature(date_str: str, absent: list[str]) -> str:
    result = greedy_assign(date_str, absent)
    return json.dumps(result["assignments"], ensure_ascii=False, sort_keys=True)


def _people_grid_signature(people_grid: dict) -> str:
    return json.dumps(people_grid, ensure_ascii=False, sort_keys=True)


def test_eval_story_rule_refine_contract_stays_on_rule_path(monkeypatch):
    api_views = _api_views()

    def _should_not_call_llm(**_kwargs):
        raise AssertionError("rule-based refine case should not hit the LLM fallback")

    monkeypatch.setattr(api_views, "parse_refine_with_llm", _should_not_call_llm)

    result = api_views.execute_monthly_refine(
        {
            "year_month": "2026-02",
            "language": "en",
            "leave_requests": {},
            "refine_text": "Spencer 2026-02-01 to D",
        }
    )

    assert result.status_code == 200
    payload = result.payload
    assert payload.get("ok") is True
    assert payload.get("parse_errors") == []
    assert payload.get("explain") == {
        "parser": "rule_based_v2",
        "ops_count": 1,
        "fallback_used": False,
    }
    assert any(
        item.get("date") == "2026-02-01"
        and item.get("person") == "Spencer"
        and (item.get("to") or {}).get("code") == "D"
        for item in (payload.get("diff") or [])
    )


def test_eval_story_refine_uses_working_state_as_base(monkeypatch):
    api_views = _api_views()
    date_str = "2025-11-05"
    preview_people_grid = {
        "year_month": "2025-11",
        "dates": [date_str],
        "rows": [{"name": "Spencer", "role": "staff", "cells": [{"code": "A", "note": ""}]}],
    }
    saved_people_grid = {
        "year_month": "2025-11",
        "dates": [date_str],
        "rows": [{"name": "Spencer", "role": "staff", "cells": [{"code": "D", "note": "saved"}]}],
    }

    def _should_not_call_llm(**_kwargs):
        raise AssertionError("working_state precedence case should stay on the rule parser path")

    monkeypatch.setattr(
        api_views,
        "_build_monthly_preview",
        lambda _inputs: {
            "people_grid": preview_people_grid,
            "warnings": ["BASE_WARNING"],
            "weekly_rest_warnings": [],
            "shift_metadata": [],
            "station_metadata": [],
        },
    )
    monkeypatch.setattr(api_views, "parse_refine_with_llm", _should_not_call_llm)

    result = api_views.execute_monthly_refine(
        {
            "year_month": "2025-11",
            "language": "en",
            "leave_requests": {},
            "working_state": {
                "people_grid": saved_people_grid,
                "warnings": ["SAVED_WARNING"],
                "weekly_rest_warnings": [],
            },
            "refine_text": "Spencer 2025-11-05 to OFF",
        }
    )

    assert result.status_code == 200
    payload = result.payload
    assert payload.get("ok") is True
    assert any(
        item.get("date") == date_str
        and (item.get("from") or {}).get("code") == "D"
        and (item.get("to") or {}).get("code") == "OFF"
        for item in (payload.get("diff") or [])
    )
    assert "SAVED_WARNING" in (payload.get("warnings") or [])
    assert "BASE_WARNING" not in (payload.get("warnings") or [])


def test_eval_story_refine_fallback_success_is_offline_and_reviewable(monkeypatch):
    api_views = _api_views()
    calls = {"count": 0}

    def _fake_llm(**_kwargs):
        calls["count"] += 1
        return {
            "ok": True,
            "commands": [
                {
                    "intent": "replace_person",
                    "date": "2026-02-01",
                    "station": "gateau",
                    "target_person": "Kim",
                }
            ],
        }

    monkeypatch.setattr(api_views, "parse_refine_with_llm", _fake_llm)

    result = api_views.execute_monthly_refine(
        {
            "year_month": "2026-02",
            "language": "en",
            "leave_requests": {},
            "refine_text": "Change gateau on 2/1 to Kim",
        }
    )

    assert result.status_code == 200
    payload = result.payload
    assert payload.get("ok") is True
    assert calls["count"] == 1
    assert payload.get("parse_errors") == []
    assert payload.get("explain") == {
        "parser": "llm_fallback_v1",
        "ops_count": 1,
        "fallback_used": True,
    }
    assert any(
        item.get("action") == "replace_station_new"
        and item.get("date") == "2026-02-01"
        and item.get("person") == "Kim"
        and item.get("station") == "gateau"
        for item in (payload.get("diff") or [])
    )


def test_eval_story_refine_fallback_failure_is_classified(monkeypatch):
    api_views = _api_views()

    def _fake_llm(**_kwargs):
        return {
            "ok": False,
            "error": {
                "code": "invalid_json",
                "message": "LLM returned invalid JSON",
            },
        }

    monkeypatch.setattr(api_views, "parse_refine_with_llm", _fake_llm)

    result = api_views.execute_monthly_refine(
        {
            "year_month": "2026-02",
            "language": "en",
            "leave_requests": {},
            "refine_text": "Masuda on 2026-02-03 should be OFF",
        }
    )

    assert result.status_code == 400
    payload = result.payload
    assert payload.get("ok") is False
    assert "Refine parse failed" in str(payload.get("detail"))
    assert any(
        item.get("code") == "llm_invalid_json"
        for item in (payload.get("parse_errors") or [])
        if isinstance(item, dict)
    )


def test_eval_story_monthly_preview_is_repeatable():
    api_views = _api_views()
    payload = {
        "year_month": "2025-11",
        "language": "en",
        "leave_requests": {"Spencer": ["2025-11-05"]},
    }
    people_grid_signatures = set()

    for _ in range(3):
        result = api_views.execute_monthly_preview(payload)
        assert result.status_code == 200
        people_grid_signatures.add(_people_grid_signature(result.payload["people_grid"]))

    assert len(people_grid_signatures) == 1


def test_eval_story_monthly_preview_does_not_mutate_daily_scheduler():
    api_views = _api_views()
    before = _daily_assignments_signature("2025-11-10", [])

    result = api_views.execute_monthly_preview(
        {
            "year_month": "2025-11",
            "language": "en",
            "leave_requests": {},
        }
    )

    assert result.status_code == 200
    after = _daily_assignments_signature("2025-11-10", [])
    assert before == after
