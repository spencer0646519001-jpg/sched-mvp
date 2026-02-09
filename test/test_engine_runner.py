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
