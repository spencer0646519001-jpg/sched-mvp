import json
import os
import sys
import types

import django
import pytest
from django.test import Client
from django.test.utils import override_settings


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_resolver_rejects_unsupported_tenant_without_json_fallback(monkeypatch):
    import app.infra.engine_input_resolver as resolver

    def fail_json_builder():
        raise AssertionError("unsupported tenants must not fall back to demo JSON inputs")

    monkeypatch.setattr(resolver, "build_inputs_from_json", fail_json_builder)

    with pytest.raises(resolver.UnsupportedEngineInputTenant) as exc_info:
        resolver.resolve_engine_inputs_for_tenant("not_demo")

    assert exc_info.value.tenant_name == "not_demo"
    assert resolver.supported_engine_input_tenants() == ["demo_kitchen"]


def test_resolver_allows_demo_tenant(monkeypatch):
    import app.infra.engine_input_resolver as resolver

    sentinel_inputs = object()
    monkeypatch.setattr(resolver, "build_inputs_from_json", lambda: sentinel_inputs)

    assert resolver.resolve_engine_inputs_for_tenant("demo_kitchen") is sentinel_inputs


def test_canonical_daily_run_rejects_unsupported_tenant_before_engine():
    _django_setup()

    payload = {"date": "2026-01-06", "absent": []}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/not_demo/daily-runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 400
    body = json.loads(response.content.decode("utf-8"))
    assert body == {
        "ok": False,
        "code": "unsupported_tenant",
        "detail": (
            "Unsupported scheduling tenant 'not_demo'. "
            "Canonical scheduling currently supports only demo_kitchen."
        ),
        "tenant_name": "not_demo",
        "supported_tenants": ["demo_kitchen"],
    }


def test_canonical_graph_run_rejects_unsupported_tenant_before_graph(monkeypatch):
    _django_setup()

    def fail_run_daily_schedule_graph(**_kwargs):
        raise AssertionError("unsupported tenants must be rejected before graph execution")

    fake_module = types.ModuleType("app.langgraph_flow")
    fake_module.run_daily_schedule_graph = fail_run_daily_schedule_graph
    monkeypatch.setitem(sys.modules, "app.langgraph_flow", fake_module)

    payload = {"date": "2026-01-06", "absent": []}
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/tenants/not_demo/daily-runs-graph/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 400
    body = json.loads(response.content.decode("utf-8"))
    assert body["ok"] is False
    assert body["code"] == "unsupported_tenant"
    assert body["tenant_name"] == "not_demo"
    assert body["supported_tenants"] == ["demo_kitchen"]


def test_monthly_scheduling_inputs_uses_shared_tenant_resolver(monkeypatch):
    import app.infra.monthly_scheduling_inputs as monthly_inputs

    sentinel_inputs = object()
    observed = {}

    def fake_resolve_engine_inputs(tenant_name):
        observed["tenant_name"] = tenant_name
        return sentinel_inputs

    monkeypatch.setattr(
        monthly_inputs,
        "resolve_engine_inputs_for_tenant",
        fake_resolve_engine_inputs,
    )
    monkeypatch.setattr(monthly_inputs, "load_workers", lambda: {"people": []})
    monkeypatch.setattr(monthly_inputs, "load_people", lambda _tenant_name: [])
    monkeypatch.setattr(
        monthly_inputs,
        "load_station_metadata_overlay",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        monthly_inputs,
        "load_shift_metadata_overlay",
        lambda **_kwargs: object(),
    )

    result = monthly_inputs.build_monthly_scheduling_inputs(
        start_date="2025-11-01",
        language="en",
        leave_requests={},
        leave_by_date={},
        tenant_name="demo_kitchen",
    )

    assert observed == {"tenant_name": "demo_kitchen"}
    assert result.engine_inputs is sentinel_inputs
