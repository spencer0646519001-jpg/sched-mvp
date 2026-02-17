from django.test import Client

from app.engine_runner import run_engine


def test_engine_runner_schema():
    out = run_engine("2025-11-10", [], seed=0)

    assert out["date"] == "2025-11-10"
    assert "is_holiday" in out
    assert "chefs_present" in out
    assert "headcount_total" in out
    assert "assignments" in out
    assert "hours_estimate" in out
    assert "warnings" in out

    assert isinstance(out["assignments"], dict)
    assert len(out["assignments"]) > 0
    assert isinstance(out["hours_estimate"], dict)


def test_root_healthcheck_mirror_shape():
    client = Client()

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_generate_day_mirror_core_shape():
    client = Client()

    resp = client.get("/api/generate/day/2025-11-10", {"absent": "Chung,Masuda"})

    assert resp.status_code == 200
    payload = resp.json()

    for key in [
        "date",
        "is_holiday",
        "chefs_present",
        "headcount_total",
        "assignments",
        "hours_estimate",
        "warnings",
    ]:
        assert key in payload
