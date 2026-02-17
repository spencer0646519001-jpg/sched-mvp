import os

import pytest

django = pytest.importorskip("django")
Client = pytest.importorskip("django.test", fromlist=["Client"]).Client
TestClient = pytest.importorskip("fastapi.testclient", fromlist=["TestClient"]).TestClient

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from app.main import app as fastapi_app  # noqa: E402


def _status_class(code: int) -> int:
    return code // 100


def _assert_payload_shape_parity(fastapi_payload, django_payload):
    assert type(fastapi_payload) is type(django_payload)

    if isinstance(fastapi_payload, dict):
        assert set(fastapi_payload.keys()) == set(django_payload.keys())
        if (
            "data" in fastapi_payload
            and "data" in django_payload
            and isinstance(fastapi_payload["data"], dict)
            and isinstance(django_payload["data"], dict)
        ):
            assert set(fastapi_payload["data"].keys()) == set(django_payload["data"].keys())


def _assert_parity(fastapi_response, django_response):
    assert _status_class(fastapi_response.status_code) == _status_class(django_response.status_code)
    _assert_payload_shape_parity(fastapi_response.json(), django_response.json())


def test_plan_endpoints_parity_harness():
    fastapi_client = TestClient(fastapi_app)
    django_client = Client()

    # POST /api/plan/create
    f_create = fastapi_client.post("/api/plan/create", json={"date": "2025-11-10"})
    d_create = django_client.post(
        "/api/plan/create",
        data='{"date": "2025-11-10"}',
        content_type="application/json",
    )
    _assert_parity(f_create, d_create)

    fastapi_plan_id = f_create.json().get("plan_id")
    django_plan_id = d_create.json().get("plan_id")

    # POST /api/plan/patch_preview
    f_preview = fastapi_client.post(
        "/api/plan/patch_preview",
        json={"plan_id": fastapi_plan_id, "text": "把 Chung 改到 GATEAU 晚班"},
    )
    d_preview = django_client.post(
        "/api/plan/patch_preview",
        data='{{"plan_id": "{}", "text": "把 Chung 改到 GATEAU 晚班"}}'.format(django_plan_id),
        content_type="application/json",
    )
    _assert_parity(f_preview, d_preview)

    # POST /api/plan/patch_apply
    f_apply = fastapi_client.post(
        "/api/plan/patch_apply",
        json={"plan_id": fastapi_plan_id, "text": "把 Chung 改到 GATEAU 晚班"},
    )
    d_apply = django_client.post(
        "/api/plan/patch_apply",
        data='{{"plan_id": "{}", "text": "把 Chung 改到 GATEAU 晚班"}}'.format(django_plan_id),
        content_type="application/json",
    )
    _assert_parity(f_apply, d_apply)

    # GET /api/plan/get
    f_get_ok = fastapi_client.get("/api/plan/get", params={"plan_id": fastapi_plan_id})
    d_get_ok = django_client.get("/api/plan/get", {"plan_id": django_plan_id})
    _assert_parity(f_get_ok, d_get_ok)

    f_get_missing = fastapi_client.get("/api/plan/get")
    d_get_missing = django_client.get("/api/plan/get")
    _assert_parity(f_get_missing, d_get_missing)

    # GET /api/plan/list
    f_list = fastapi_client.get("/api/plan/list")
    d_list = django_client.get("/api/plan/list")
    _assert_parity(f_list, d_list)

    # DELETE /api/plan/delete
    f_delete_ok = fastapi_client.delete("/api/plan/delete", params={"plan_id": fastapi_plan_id})
    d_delete_ok = django_client.delete("/api/plan/delete?plan_id={}".format(django_plan_id))
    _assert_parity(f_delete_ok, d_delete_ok)

    f_delete_missing = fastapi_client.delete("/api/plan/delete")
    d_delete_missing = django_client.delete("/api/plan/delete")
    _assert_parity(f_delete_missing, d_delete_missing)
