import json
import os

from django.test import Client
from django.test.utils import override_settings
import django


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_monthly_preview_success_shape_and_off_code():
    _django_setup()

    payload = {
        "year_month": "2025-11",
        "language": "ja",
        "leave_requests": {
            "Spencer": ["2025-11-05"],
        },
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))

    assert data["meta"]["month_start"] == "2025-11-01"
    assert data["meta"]["language"] == "ja"
    assert "2025-11-05" in data["dates"]
    assert "Spencer" in data["grid"]
    assert data["grid"]["Spencer"]["2025-11-05"]["code"] == "OFF"
    assert "people_grid" in data
    assert "legend" in data
    assert "" in data["legend"]
    assert "OFF" in data["legend"]

    grid_codes = {
        cell.get("code", "")
        for row in data["people_grid"].get("rows", [])
        for cell in row.get("cells", [])
        if cell.get("code", "")
    }
    known_codes = {"A", "B", "C", "D", "1", "2", "3", "4"}
    if grid_codes.intersection(known_codes):
        assert any(code in data["legend"] for code in grid_codes.intersection(known_codes))


def test_monthly_preview_invalid_year_month_returns_400():
    _django_setup()

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/preview",
            data=json.dumps({"year_month": "2025/11"}),
            content_type="application/json",
        )

    assert response.status_code == 400


def test_monthly_preview_invalid_leave_requests_returns_400():
    _django_setup()

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/preview",
            data=json.dumps({"year_month": "2025-11", "leave_requests": ["bad"]}),
            content_type="application/json",
        )

    assert response.status_code == 400


def test_monthly_preview_weekly_rest_warnings_for_full_week(monkeypatch):
    _django_setup()

    import core.api_views_monthly as api_views

    week_dates = [
        "2026-01-26",
        "2026-01-27",
        "2026-01-28",
        "2026-01-29",
        "2026-01-30",
        "2026-01-31",
        "2026-02-01",
    ]

    plan = {}
    for date_str in week_dates[:-1]:
        plan[date_str] = {
            "assignments": {
                "gateau": [{"name": "Spencer", "shift": "A"}],
            },
            "warnings": [],
            "chefs_present": [],
        }
    plan[week_dates[-1]] = {
        "assignments": {},
        "warnings": [],
        "chefs_present": [],
    }

    fake_state = {
        "month_start": week_dates[0],
        "month_end": week_dates[-1],
        "plan": plan,
        "summary": {},
        "overtime": {},
    }

    monkeypatch.setattr(
        api_views,
        "_generate_month_state_with_leave_requests",
        lambda start_date_str, leave_by_date, engine_inputs=None: fake_state,
    )

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/preview",
            data=json.dumps({"year_month": "2026-01", "leave_requests": {}}),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))

    assert "weekly_rest_warnings" in data
    assert any(
        w.get("type") == "weekly_rest"
        and w.get("person") == "Spencer"
        and w.get("week") == "2026-W05"
        and w.get("days_off") == 1
        and w.get("required") == 2
        for w in data["weekly_rest_warnings"]
    )


def test_monthly_preview_weekly_rest_leave_days_count_as_off(monkeypatch):
    _django_setup()

    import core.api_views_monthly as api_views

    week_dates = [
        "2026-01-26",
        "2026-01-27",
        "2026-01-28",
        "2026-01-29",
        "2026-01-30",
        "2026-01-31",
        "2026-02-01",
    ]

    # Spencer works 5 days, and has leave on the remaining 2 days.
    plan = {}
    for date_str in week_dates[:5]:
        plan[date_str] = {
            "assignments": {
                "gateau": [{"name": "Spencer", "shift": "A"}],
            },
            "warnings": [],
            "chefs_present": [],
        }
    for date_str in week_dates[5:]:
        plan[date_str] = {
            "assignments": {},
            "warnings": [],
            "chefs_present": [],
        }

    fake_state = {
        "month_start": week_dates[0],
        "month_end": week_dates[-1],
        "plan": plan,
        "summary": {},
        "overtime": {},
    }

    monkeypatch.setattr(
        api_views,
        "_generate_month_state_with_leave_requests",
        lambda start_date_str, leave_by_date, engine_inputs=None: fake_state,
    )

    payload = {
        "year_month": "2026-01",
        "leave_requests": {"Spencer": [week_dates[5], week_dates[6]]},
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert not any(
        w.get("type") == "weekly_rest"
        and w.get("person") == "Spencer"
        and w.get("week") == "2026-W05"
        for w in data["weekly_rest_warnings"]
    )
