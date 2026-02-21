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
