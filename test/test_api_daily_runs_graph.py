import builtins
import json
import os
import sys
import types

import django
from django.test import Client
from django.test.utils import override_settings


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_daily_runs_graph_returns_unified_explain_contract(monkeypatch):
    _django_setup()

    def fake_run_daily_schedule_graph(*, tenant_name, date_str, absent=None):
        assert tenant_name == "demo_kitchen"
        assert date_str == "2026-01-06"
        assert absent == ["Kim"]
        return {
            "ok": True,
            "data": {
                "out": {
                    "assignments": {"gateau": "Kim"},
                    "warnings": [],
                    "chefs_present": [],
                    "headcount_total": 1,
                },
                "decision_trace": [{"station": "gateau", "picked": ["Kim"]}],
                "explanations": {"gateau": "Picked Kim from skilled pool."},
                "metrics": {"fallback_stations": 0},
            },
        }

    fake_module = types.ModuleType("app.langgraph_flow")
    fake_module.run_daily_schedule_graph = fake_run_daily_schedule_graph
    monkeypatch.setitem(sys.modules, "app.langgraph_flow", fake_module)

    payload = {"date": "2026-01-06", "absent": ["Kim"]}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/demo_kitchen/daily-runs-graph/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    body = json.loads(response.content.decode("utf-8"))
    assert body["ok"] is True
    assert body["date"] == "2026-01-06"
    assert isinstance(body["summary"], str) and body["summary"]
    assert isinstance(body["trace"], list) and body["trace"]
    assert isinstance(body["text"], str) and "gateau" in body["text"]
    assert body["data"]["out"]["ok"] is True


def test_daily_runs_graph_langgraph_unavailable_returns_json_detail(monkeypatch):
    _django_setup()

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.langgraph_flow":
            raise ModuleNotFoundError("No module named 'langgraph'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    payload = {"date": "2026-01-06"}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/demo_kitchen/daily-runs-graph/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 501
    body = json.loads(response.content.decode("utf-8"))
    assert body["ok"] is False
    assert "langgraph" in body["detail"]
