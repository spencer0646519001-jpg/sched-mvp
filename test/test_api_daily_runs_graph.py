import builtins
import json
import os
import sys
import types

import django
from django.test import Client
from django.test.utils import override_settings

from app.infra.shift_metadata import build_shift_metadata_overlay
from app.infra.station_metadata import build_station_metadata_overlay


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_daily_runs_graph_returns_unified_explain_contract(monkeypatch):
    _django_setup()

    def fake_run_daily_schedule_graph(*, tenant_name, date_str, absent=None, language=None):
        assert tenant_name == "demo_kitchen"
        assert date_str == "2026-01-06"
        assert absent == ["Kim"]
        assert language == "en"
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

    payload = {"date": "2026-01-06", "absent": ["Kim"], "language": "en"}
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


def test_daily_runs_graph_forwards_language_and_localizes_summary(monkeypatch):
    _django_setup()

    def fake_run_daily_schedule_graph(*, tenant_name, date_str, absent=None, language=None):
        assert tenant_name == "demo_kitchen"
        assert date_str == "2026-01-06"
        assert absent == []
        assert language == "ja"
        return {
            "ok": True,
            "data": {
                "out": {
                    "assignments": {"gateau": []},
                    "warnings": [],
                    "chefs_present": [],
                    "headcount_total": 0,
                },
                "decision_trace": [{"station": "gateau", "picked": []}],
                "explanations": {"gateau": "この站位には割当がありません。"},
                "metrics": {"fallback_stations": 0},
            },
        }

    fake_module = types.ModuleType("app.langgraph_flow")
    fake_module.run_daily_schedule_graph = fake_run_daily_schedule_graph
    monkeypatch.setitem(sys.modules, "app.langgraph_flow", fake_module)

    payload = {"date": "2026-01-06", "language": "ja"}
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
    assert "説明" in body["summary"]


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


def test_daily_runs_graph_adds_station_labels_from_station_metadata_overlay(monkeypatch):
    _django_setup()

    def fake_run_daily_schedule_graph(*, tenant_name, date_str, absent=None, language=None):
        assert tenant_name == "demo_kitchen"
        assert date_str == "2026-01-06"
        return {
            "ok": True,
            "data": {
                "out": {
                    "assignments": {"gateau": [{"name": "Kim", "shift": "A"}]},
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
    monkeypatch.setattr(
        "core.api_views_daily.load_station_metadata_overlay",
        lambda **kwargs: build_station_metadata_overlay(
            base_station_codes=["gateau"],
            db_station_rows=[
                {
                    "code": "gateau",
                    "display_name": "Gateau Counter",
                    "is_active": True,
                    "sort_order": 25,
                }
            ],
        ),
    )

    payload = {"date": "2026-01-06", "language": "en"}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/demo_kitchen/daily-runs-graph/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    body = json.loads(response.content.decode("utf-8"))
    assert body["trace"][0]["station"] == "gateau"
    assert body["trace"][0]["station_label"] == "Gateau Counter"
    assert body["station_labels"] == {"gateau": "Gateau Counter"}
    assert body["station_metadata"] == [
        {
            "code": "gateau",
            "display_name": "Gateau Counter",
            "is_active": True,
            "sort_order": 25,
        }
    ]


def test_daily_runs_graph_adds_db_shift_metadata_to_trace_and_payload(monkeypatch):
    _django_setup()

    def fake_run_daily_schedule_graph(*, tenant_name, date_str, absent=None, language=None):
        assert tenant_name == "demo_kitchen"
        assert date_str == "2026-01-06"
        return {
            "ok": True,
            "data": {
                "out": {
                    "assignments": {
                        "gateau": [
                            {"name": "Kim", "shift": "A"},
                            {"name": "Masuda", "shift": "D"},
                        ]
                    },
                    "warnings": [],
                    "chefs_present": [],
                    "headcount_total": 2,
                },
                "decision_trace": [{"station": "gateau", "picked": ["Kim", "Masuda"]}],
                "explanations": {"gateau": "Picked Kim and Masuda from available pool."},
                "metrics": {"fallback_stations": 0},
            },
        }

    fake_module = types.ModuleType("app.langgraph_flow")
    fake_module.run_daily_schedule_graph = fake_run_daily_schedule_graph
    monkeypatch.setitem(sys.modules, "app.langgraph_flow", fake_module)
    monkeypatch.setattr(
        "core.api_views_daily.load_shift_metadata_overlay",
        lambda **kwargs: build_shift_metadata_overlay(
            base_shift_defs=kwargs["base_shift_defs"],
            db_shift_rows=[
                {
                    "code": "A",
                    "display_name": "Morning Prep",
                    "legend_label": "Morning Prep shift",
                    "paid_hours": 7.5,
                },
                {
                    "code": "D",
                    "display_name": "ClosingD",
                    "legend_label": "Closing D shift",
                    "paid_hours": 8.5,
                },
            ],
        ),
    )

    payload = {"date": "2026-01-06", "language": "en"}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/demo_kitchen/daily-runs-graph/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    body = json.loads(response.content.decode("utf-8"))
    shift_metadata_by_code = {item["code"]: item for item in body["shift_metadata"]}
    assert shift_metadata_by_code["A"]["display_name"] == "Morning Prep"
    assert shift_metadata_by_code["A"]["label"] == "Morning Prep shift"
    assert shift_metadata_by_code["A"]["paid_hours"] == 7.5
    assert shift_metadata_by_code["D"]["display_name"] == "ClosingD"
    assert shift_metadata_by_code["D"]["label"] == "Closing D shift"
    assert shift_metadata_by_code["D"]["paid_hours"] == 8.5

    trace_item = body["trace"][0]
    assert trace_item["picked_details"] == [
        {
            "name": "Kim",
            "shift": "A",
            "shift_display_name": "Morning Prep",
            "shift_legend_label": "Morning Prep shift",
            "shift_label": "Morning Prep shift",
            "shift_paid_hours": 7.5,
        },
        {
            "name": "Masuda",
            "shift": "D",
            "shift_display_name": "ClosingD",
            "shift_legend_label": "Closing D shift",
            "shift_label": "Closing D shift",
            "shift_paid_hours": 8.5,
        },
    ]
    assert body["data"]["decision_trace"][0]["picked_details"] == trace_item["picked_details"]
    assert body["data"]["shift_metadata"] == body["shift_metadata"]
    assert body["data"]["out"]["data"]["assignments"][0]["assignees"][0]["shift"] == "A"


def test_daily_runs_graph_real_graph_populates_trace_derived_metrics():
    _django_setup()

    payload = {"date": "2026-01-06", "absent": ["Kim"], "language": "en"}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/demo_kitchen/daily-runs-graph/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    body = json.loads(response.content.decode("utf-8"))
    trace = body["trace"]
    metrics = body["metrics"]
    fallback_station_count = sum(1 for item in trace if item.get("has_fallback"))

    assert body["ok"] is True
    assert body["date"] == "2026-01-06"
    assert isinstance(trace, list) and trace
    assert body["data"]["decision_trace"] == trace
    assert body["data"]["metrics"] == metrics
    assert metrics["stations_total"] == len(trace)
    assert metrics["fallback_stations"] == fallback_station_count
    assert "explanations" in body
    assert "station_metadata" in body
    assert "shift_metadata" in body
