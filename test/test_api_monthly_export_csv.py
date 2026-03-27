import csv
import io
import json
import os

from django.test import Client
from django.test.utils import override_settings
import django


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_monthly_export_csv_success():
    _django_setup()

    payload = {
        "year_month": "2025-11",
        "language": "ja",
        "leave_requests": {"Spencer": ["2025-11-05"]},
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/export.csv",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    assert "text/csv" in response["Content-Type"]

    text = response.content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) >= 2

    header = rows[0]
    assert header[0:2] == ["name", "role"]
    assert any(col.startswith("2025-11-") for col in header[2:])


def test_monthly_export_csv_applies_leave_requests(monkeypatch):
    _django_setup()

    import core.api_views_monthly as api_views

    date_str = "2025-11-05"
    fake_state = {
        "month_start": date_str,
        "month_end": date_str,
        "plan": {
            date_str: {
                "assignments": {},
                "warnings": [],
                "chefs_present": [],
            }
        },
        "summary": {},
        "overtime": {},
    }

    monkeypatch.setattr(
        api_views,
        "_generate_month_state_with_leave_requests",
        lambda start_date_str, leave_by_date, engine_inputs=None: fake_state,
    )

    payload = {
        "year_month": "2025-11",
        "language": "ja",
        "leave_requests": {"Spencer": [date_str]},
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/export.csv",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    header = rows[0]
    date_idx = header.index(date_str)

    spencer_row = next(r for r in rows[1:] if r and r[0] == "Spencer")
    assert spencer_row[date_idx] == "OFF"


def test_monthly_export_csv_uses_provided_working_people_grid(monkeypatch):
    _django_setup()

    import core.api_views_monthly as api_views

    def _unexpected_preview(_scheduling_inputs):
        raise AssertionError("export should use the provided working_people_grid")

    monkeypatch.setattr(api_views, "_build_monthly_preview", _unexpected_preview)

    date_str = "2025-11-05"
    payload = {
        "year_month": "2025-11",
        "language": "ja",
        "leave_requests": {},
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
        },
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/export.csv",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    header = rows[0]
    date_idx = header.index(date_str)

    spencer_row = next(r for r in rows[1:] if r and r[0] == "Spencer")
    assert spencer_row[date_idx] == "OFF"
