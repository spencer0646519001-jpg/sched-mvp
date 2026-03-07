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
