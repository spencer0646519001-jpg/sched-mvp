import json
import os

import django
import pytest
from django.test import Client
from django.test.utils import override_settings

from app.infra.shift_metadata import build_shift_metadata_overlay
from app.infra.station_metadata import build_station_metadata_overlay


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_monthly_refine_returns_diff_and_preview_people_grid():
    _django_setup()

    payload = {
        "year_month": "2025-11",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Spencer 2025-11-05 to OFF",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert isinstance(data.get("diff"), list)
    assert isinstance(data.get("preview_people_grid"), dict)
    assert isinstance(data.get("warnings"), list)
    assert isinstance(data.get("weekly_rest_warnings"), list)
    assert any(item.get("date") == "2025-11-05" for item in data["diff"])


def test_monthly_refine_empty_text_returns_warning_but_200():
    _django_setup()

    payload = {
        "year_month": "2025-11",
        "language": "en",
        "leave_requests": {},
        "refine_text": "",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert "REFINE_TEXT_EMPTY" in (data.get("warnings") or [])


def test_monthly_refine_parses_person_day_shift_change_with_short_date():
    _django_setup()

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Spencer 2/1號變成D",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert any(
        item.get("date") == "2026-02-01" and item.get("person") == "Spencer" and (item.get("to") or {}).get("code") == "D"
        for item in (data.get("diff") or [])
    )


def test_monthly_refine_parses_person_day_off_synonym():
    _django_setup()

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Spencer 2/1 休假",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert any(
        item.get("date") == "2026-02-01" and (item.get("to") or {}).get("code") == "OFF"
        for item in (data.get("diff") or [])
    )


def test_monthly_refine_parse_failure_returns_readable_error():
    _django_setup()

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Spencer 改成 D",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 400
    data = json.loads(response.content.decode("utf-8"))
    assert "Refine parse failed" in str(data.get("detail"))
    assert isinstance(data.get("parse_errors"), list)
    assert data["parse_errors"]
    assert data["parse_errors"][0].get("code") in {"invalid_date", "unparsed_command", "date_not_in_month"}


def test_monthly_refine_parses_station_replace_person_with_short_date():
    _django_setup()

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "2/1 gateau 改成 Kim",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert any(
        item.get("action") == "replace_station_new"
        and item.get("date") == "2026-02-01"
        and item.get("person") == "Kim"
        and item.get("station") == "gateau"
        for item in (data.get("diff") or [])
    )


def test_monthly_refine_parses_station_add_with_alias():
    _django_setup()

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "2/1 misen 增加一個人",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert any(
        item.get("action") == "add_station"
        and item.get("date") == "2026-02-01"
        and item.get("station") == "mise_en_place"
        for item in (data.get("diff") or [])
    )


def test_monthly_refine_uses_db_station_display_name_for_lookup_and_diff_label(monkeypatch):
    _django_setup()
    overlay = build_station_metadata_overlay(
        base_station_codes=["gateau", "petit_four", "glaze_and_fruit", "mise_en_place"],
        db_station_rows=[
            {
                "code": "gateau",
                "display_name": "Gateau Counter",
                "is_active": True,
                "sort_order": 25,
            }
        ],
    )
    monkeypatch.setattr(
        "app.infra.monthly_scheduling_inputs.load_station_metadata_overlay",
        lambda **kwargs: overlay,
    )

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "2/1 Gateau Counter to Kim",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert any(
        item.get("action") == "replace_station_new"
        and item.get("date") == "2026-02-01"
        and item.get("person") == "Kim"
        and item.get("station") == "gateau"
        and item.get("station_label") == "Gateau Counter"
        for item in (data.get("diff") or [])
    )
    assert any(
        item.get("code") == "gateau" and item.get("display_name") == "Gateau Counter"
        for item in (data.get("station_metadata") or [])
    )


def test_monthly_refine_accepts_db_shift_display_name_for_set_shift(monkeypatch):
    _django_setup()
    monkeypatch.setattr(
        "app.infra.monthly_scheduling_inputs.load_shift_metadata_overlay",
        lambda **kwargs: build_shift_metadata_overlay(
            base_shift_defs=kwargs["base_shift_defs"],
            db_shift_rows=[
                {
                    "code": "D",
                    "display_name": "ClosingD",
                    "legend_label": "Closing D shift",
                    "paid_hours": 8.5,
                }
            ],
        ),
    )

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Spencer 2026-02-01 to ClosingD",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert any(
        item.get("date") == "2026-02-01"
        and item.get("person") == "Spencer"
        and (item.get("to") or {}).get("code") == "D"
        for item in (data.get("diff") or [])
    )
    assert any(
        item.get("code") == "D"
        and item.get("display_name") == "ClosingD"
        and item.get("label") == "Closing D shift"
        for item in (data.get("shift_metadata") or [])
    )


def test_monthly_refine_rule_parser_success_does_not_call_llm_fallback(monkeypatch):
    _django_setup()
    calls = {"count": 0}

    def _fake_llm(**kwargs):
        calls["count"] += 1
        return {"ok": False, "error": {"code": "should_not_be_called", "message": "should_not_be_called"}}

    monkeypatch.setattr("core.api_views_monthly.parse_refine_with_llm", _fake_llm)

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Spencer 2026-02-01 to D",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert calls["count"] == 0
    explain = data.get("explain") or {}
    assert explain.get("parser") == "rule_based_v2"
    assert explain.get("fallback_used") is False


def test_monthly_refine_calls_llm_fallback_when_rule_parser_fails(monkeypatch):
    _django_setup()
    calls = {"count": 0}

    def _fake_llm(**kwargs):
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

    monkeypatch.setattr("core.api_views_monthly.parse_refine_with_llm", _fake_llm)

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Change gateau on 2/1 to Kim",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert calls["count"] == 1
    explain = data.get("explain") or {}
    assert explain.get("parser") == "llm_fallback_v1"
    assert explain.get("fallback_used") is True
    assert any(
        item.get("action") == "replace_station_new"
        and item.get("date") == "2026-02-01"
        and item.get("person") == "Kim"
        and item.get("station") == "gateau"
        for item in (data.get("diff") or [])
    )


def test_monthly_refine_llm_invalid_json_returns_readable_error(monkeypatch):
    _django_setup()

    def _fake_llm(**kwargs):
        return {
            "ok": False,
            "error": {
                "code": "invalid_json",
                "message": "LLM returned invalid JSON",
            },
        }

    monkeypatch.setattr("core.api_views_monthly.parse_refine_with_llm", _fake_llm)

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Masuda on 2026-02-03 should be OFF",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 400
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is False
    assert "Refine parse failed" in str(data.get("detail"))
    parse_errors = data.get("parse_errors") or []
    assert parse_errors
    assert any(item.get("code") == "llm_invalid_json" for item in parse_errors if isinstance(item, dict))


@pytest.mark.parametrize(
    "text,llm_result,expected_action",
    [
        (
            "讓 2/1 Ishikawa 休",
            {
                "ok": True,
                "commands": [
                    {
                        "intent": "set_shift",
                        "date": "2/1",
                        "person": "Ishikawa",
                        "shift": "OFF",
                    }
                ],
            },
            "set_off",
        ),
        (
            "2月1號 Ishikawa 改成休假",
            {
                "ok": True,
                "commands": [
                    {
                        "intent": "set_shift",
                        "date": "2月1號",
                        "person": "Ishikawa",
                        "shift": "OFF",
                    }
                ],
            },
            "set_off",
        ),
        (
            "幫我把 Spencer 2/1 改成 D",
            {
                "ok": True,
                "commands": [
                    {
                        "intent": "set_shift",
                        "date": "2/1",
                        "person": "Spencer",
                        "shift": "D",
                    }
                ],
            },
            "set_shift",
        ),
        (
            "把 2/1 的 gateau 換成 Kim",
            {
                "ok": True,
                "commands": [
                    {
                        "intent": "replace_person",
                        "date": "2/1",
                        "station": "gateau",
                        "target_person": "Kim",
                    }
                ],
            },
            "replace_station_new",
        ),
        (
            "2/1 oven 再補一個人",
            {
                "ok": True,
                "commands": [
                    {
                        "intent": "add_person",
                        "date": "2/1",
                        "station": "oven",
                    }
                ],
            },
            "add_station",
        ),
    ],
)
def test_monthly_refine_llm_nlu_handles_natural_language_cases(monkeypatch, text, llm_result, expected_action):
    _django_setup()

    def _force_rule_parser_fail(*args, **kwargs):
        return [], [], [{"line": text, "code": "unparsed_command", "message": "unparsed"}]

    monkeypatch.setattr("core.api_views_monthly._parse_refine_text", _force_rule_parser_fail)
    monkeypatch.setattr("core.api_views_monthly.parse_refine_with_llm", lambda **kwargs: llm_result)

    payload = {
        "year_month": "2026-02",
        "language": "zh",
        "leave_requests": {},
        "refine_text": text,
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    explain = data.get("explain") or {}
    assert explain.get("parser") == "llm_fallback_v1"
    assert explain.get("fallback_used") is True
    assert any(item.get("action") == expected_action for item in (data.get("diff") or []))


def test_monthly_refine_llm_free_text_result_is_coerced_to_command(monkeypatch):
    _django_setup()

    def _force_rule_parser_fail(*args, **kwargs):
        return [], [], [{"line": "free", "code": "unparsed_command", "message": "unparsed"}]

    def _fake_llm(**kwargs):
        return {
            "ok": True,
            "raw_response": "intent=set_shift date=2/1 person=Ishikawa shift=OFF",
        }

    monkeypatch.setattr("core.api_views_monthly._parse_refine_text", _force_rule_parser_fail)
    monkeypatch.setattr("core.api_views_monthly.parse_refine_with_llm", _fake_llm)

    payload = {
        "year_month": "2026-02",
        "language": "en",
        "leave_requests": {},
        "refine_text": "Ishikawa off on 2/1",
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/refine",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data.get("ok") is True
    assert any(
        item.get("action") == "set_off" and item.get("date") == "2026-02-01" and item.get("person") == "Ishikawa"
        for item in (data.get("diff") or [])
    )
