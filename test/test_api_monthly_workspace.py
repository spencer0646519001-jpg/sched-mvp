import json
import os

import django
from django.test import Client
from django.test.utils import override_settings


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def _delete_workspace(year_month: str) -> None:
    from core.models import MonthlyWorkspace

    MonthlyWorkspace.objects.filter(
        tenant__name="demo_kitchen",
        year_month=year_month,
    ).delete()


def _working_state(code: str, *, year_month: str, date_str: str, note: str = "") -> dict:
    return {
        "people_grid": {
            "year_month": year_month,
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": code, "note": note}],
                }
            ],
        },
        "warnings": ["SAVED_WARNING"],
        "weekly_rest_warnings": [],
    }


def test_monthly_workspace_save_persists_valid_working_state():
    _django_setup()
    _delete_workspace("2040-01")

    payload = {
        "year_month": "2040-01",
        "leave_requests": {"Spencer": ["2040-01-05"]},
        "working_state": _working_state("OFF", year_month="2040-01", date_str="2040-01-05", note="saved"),
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/workspace/save",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    body = json.loads(response.content.decode("utf-8"))
    assert body["ok"] is True
    assert body["workspace"]["year_month"] == "2040-01"
    assert body["workspace"]["revision"] == 1

    from core.monthly_workspace_persistence import load_monthly_workspace

    saved = load_monthly_workspace(tenant_name="demo_kitchen", year_month="2040-01")
    assert saved is not None
    assert saved["leave_requests"] == {"Spencer": ["2040-01-05"]}
    assert saved["working_state"]["people_grid"]["rows"][0]["cells"][0]["code"] == "OFF"


def test_monthly_workspace_save_requires_working_state():
    _django_setup()
    _delete_workspace("2040-02")

    payload = {
        "year_month": "2040-02",
        "leave_requests": {},
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/workspace/save",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 400
    body = json.loads(response.content.decode("utf-8"))
    assert body["detail"] == "Current monthly working state is required to save."


def test_monthly_workspace_save_overwrites_same_month_and_increments_revision():
    _django_setup()
    _delete_workspace("2040-03")

    first_payload = {
        "year_month": "2040-03",
        "leave_requests": {},
        "working_state": _working_state("D", year_month="2040-03", date_str="2040-03-05"),
    }
    second_payload = {
        "year_month": "2040-03",
        "leave_requests": {"Kim": ["2040-03-02"]},
        "working_state": _working_state("OFF", year_month="2040-03", date_str="2040-03-05", note="updated"),
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        first_response = client.post(
            "/api/monthly/workspace/save",
            data=json.dumps(first_payload),
            content_type="application/json",
        )
        second_response = client.post(
            "/api/monthly/workspace/save",
            data=json.dumps(second_payload),
            content_type="application/json",
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    body = json.loads(second_response.content.decode("utf-8"))
    assert body["workspace"]["revision"] == 2

    from core.monthly_workspace_persistence import load_monthly_workspace

    saved = load_monthly_workspace(tenant_name="demo_kitchen", year_month="2040-03")
    assert saved is not None
    assert saved["leave_requests"] == {"Kim": ["2040-03-02"]}
    assert saved["working_state"]["people_grid"]["rows"][0]["cells"][0]["code"] == "OFF"
