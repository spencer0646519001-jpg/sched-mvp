import json
import os

import django
from django.test import Client
from django.test.utils import override_settings


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
