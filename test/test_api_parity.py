import os
import sys
import pytest

# Mark as legacy by default so normal pytest runs exclude this module via pytest.ini.
# If this file is explicitly targeted, run it regardless of the default marker filter.
if any(arg.endswith("test/test_api_parity.py") or arg.endswith("test_api_parity.py") for arg in sys.argv):
    pytestmark = []
else:
    pytestmark = pytest.mark.legacy


def _django_setup():
    """
    Ensure Django is configured when running under pytest (not manage.py test).
    We avoid calling django.setup() at import time to prevent pytest collection errors.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django = pytest.importorskip("django")
    django.setup()
    return django


def _status_class(code: int) -> int:
    return code // 100


def _assert_payload_shape_parity(fastapi_payload, django_payload):
    assert type(fastapi_payload) is type(django_payload)

    if isinstance(fastapi_payload, dict):
        assert set(fastapi_payload.keys()) == set(django_payload.keys())

        f_data = fastapi_payload.get("data")
        d_data = django_payload.get("data")
        if isinstance(f_data, dict) and isinstance(d_data, dict):
            assert set(f_data.keys()) == set(d_data.keys())


def _assert_parity(fastapi_response, django_response):
    assert _status_class(fastapi_response.status_code) == _status_class(django_response.status_code)

    # FastAPI TestClient response has .json()
    f_json = fastapi_response.json()

    # Django JsonResponse doesn't always have .json() depending on Django version;
    # parse from content safely.
    try:
        d_json = django_response.json()
    except Exception:
        import json

        d_json = json.loads(django_response.content.decode("utf-8"))

    _assert_payload_shape_parity(f_json, d_json)


def _assert_csv_parity(fastapi_response, django_response):
    assert _status_class(fastapi_response.status_code) == _status_class(django_response.status_code)
    assert "content-type" in {k.lower() for k in fastapi_response.headers.keys()}
    assert "content-type" in {k.lower() for k in django_response.headers.keys()}
    assert "content-disposition" in {k.lower() for k in fastapi_response.headers.keys()}
    assert "content-disposition" in {k.lower() for k in django_response.headers.keys()}


def test_plan_endpoints_parity_harness():
    # ---- setup dependencies lazily (avoid pytest collection-time failures) ----
    _django_setup()

    django_test = pytest.importorskip("django.test")
    django_utils = pytest.importorskip("django.test.utils")
    fastapi_testclient = pytest.importorskip("fastapi.testclient")

    Client = django_test.Client
    override_settings = django_utils.override_settings
    TestClient = fastapi_testclient.TestClient

    from app.main import app as fastapi_app

    fastapi_client = TestClient(fastapi_app)

    # Ensure Django test client host won't be rejected
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        django_client = Client()

        # POST /api/plan/create
        f_create = fastapi_client.post("/api/plan/create", json={"date": "2025-11-10"})
        d_create = django_client.post(
            "/api/plan/create",
            data='{"date": "2025-11-10"}',
            content_type="application/json",
        )
        _assert_parity(f_create, d_create)

        import json

        fastapi_plan_id = f_create.json().get("plan_id")
        django_plan_id = json.loads(d_create.content.decode("utf-8")).get("plan_id")

        # POST /api/plan/patch_preview
        f_preview = fastapi_client.post(
            "/api/plan/patch_preview",
            json={"plan_id": fastapi_plan_id, "text": "把 Chung 改到 GATEAU 晚班"},
        )
        d_preview = django_client.post(
            "/api/plan/patch_preview",
            data=json.dumps({"plan_id": django_plan_id, "text": "把 Chung 改到 GATEAU 晚班"}),
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
            data=json.dumps({"plan_id": django_plan_id, "text": "把 Chung 改到 GATEAU 晚班"}),
            content_type="application/json",
        )
        _assert_parity(f_apply, d_apply)

        # GET /api/plan/get (ok)
        f_get_ok = fastapi_client.get("/api/plan/get", params={"plan_id": fastapi_plan_id})
        d_get_ok = django_client.get("/api/plan/get", {"plan_id": django_plan_id})
        _assert_parity(f_get_ok, d_get_ok)

        # GET /api/plan/get (missing)
        f_get_missing = fastapi_client.get("/api/plan/get")
        d_get_missing = django_client.get("/api/plan/get")
        _assert_parity(f_get_missing, d_get_missing)

        # GET /api/plan/list
        f_list = fastapi_client.get("/api/plan/list")
        d_list = django_client.get("/api/plan/list")
        _assert_parity(f_list, d_list)

        # DELETE /api/plan/delete (ok)
        f_delete_ok = fastapi_client.delete("/api/plan/delete", params={"plan_id": fastapi_plan_id})
        d_delete_ok = django_client.delete(f"/api/plan/delete?plan_id={django_plan_id}")
        _assert_parity(f_delete_ok, d_delete_ok)

        # DELETE /api/plan/delete (missing)
        f_delete_missing = fastapi_client.delete("/api/plan/delete")
        d_delete_missing = django_client.delete("/api/plan/delete")
        _assert_parity(f_delete_missing, d_delete_missing)


def test_week_month_calendar_endpoints_parity_harness():
    _django_setup()

    django_test = pytest.importorskip("django.test")
    django_utils = pytest.importorskip("django.test.utils")
    fastapi_testclient = pytest.importorskip("fastapi.testclient")

    Client = django_test.Client
    override_settings = django_utils.override_settings
    TestClient = fastapi_testclient.TestClient

    from app.main import app as fastapi_app

    fastapi_client = TestClient(fastapi_app)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        django_client = Client()

        f_week = fastapi_client.get("/api/week", params={"start_date": "2025-11-10", "days": 7})
        d_week = django_client.get("/api/week", {"start_date": "2025-11-10", "days": 7})
        _assert_parity(f_week, d_week)

        f_week_summary = fastapi_client.get("/api/week/summary", params={"start_date": "2025-11-10", "days": 7})
        d_week_summary = django_client.get("/api/week/summary", {"start_date": "2025-11-10", "days": 7})
        _assert_parity(f_week_summary, d_week_summary)

        f_month = fastapi_client.get("/api/month", params={"start_date": "2025-11-10"})
        d_month = django_client.get("/api/month", {"start_date": "2025-11-10"})
        _assert_parity(f_month, d_month)

        f_calendar_month = fastapi_client.get("/api/calendar/month", params={"start_date": "2025-11-10"})
        d_calendar_month = django_client.get("/api/calendar/month", {"start_date": "2025-11-10"})
        _assert_parity(f_calendar_month, d_calendar_month)

        f_week_csv = fastapi_client.get("/api/week_csv", params={"start_date": "2025-11-10", "days": 7})
        d_week_csv = django_client.get("/api/week_csv", {"start_date": "2025-11-10", "days": 7})
        _assert_csv_parity(f_week_csv, d_week_csv)

        f_month_csv = fastapi_client.get("/api/month_csv", params={"start_date": "2025-11-10"})
        d_month_csv = django_client.get("/api/month_csv", {"start_date": "2025-11-10"})
        _assert_csv_parity(f_month_csv, d_month_csv)

        f_calendar_month_csv = fastapi_client.get("/api/calendar/month_csv", params={"start_date": "2025-11-10"})
        d_calendar_month_csv = django_client.get("/api/calendar/month_csv", {"start_date": "2025-11-10"})
        _assert_csv_parity(f_calendar_month_csv, d_calendar_month_csv)
