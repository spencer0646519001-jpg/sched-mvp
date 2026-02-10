from app.engine_core import run_engine
from app.generate_day import EngineInputs


def test_engine_core_schema():
    inputs = EngineInputs(
        shifts_list=[
            {"code": "A", "paid_hours": 8.0},
            {"code": "B", "paid_hours": 8.0},
        ],
        rules={
            "stations": {"gateau": 1, "petit_four": 1},
            "min_staff_weekday": 2,
            "min_staff_weekend": 2,
            "max_staff_per_day": 2,
            "allow_fallback_when_short": True,
            "require_one_chef": False,
        },
        calendar={"holidays": []},
        people=[
            {
                "name": "Kim",
                "role": "staff",
                "station_skills": ["gateau"],
                "shift_prefs": ["A"],
            },
            {
                "name": "Spencer",
                "role": "staff",
                "station_skills": ["petit_four"],
                "shift_prefs": ["B"],
            },
        ],
        station_order=["gateau", "petit_four"],
    )

    out = run_engine("2025-11-10", [], inputs, seed=0)

    assert out["date"] == "2025-11-10"
    assert "is_holiday" in out
    assert "chefs_present" in out
    assert "headcount_total" in out
    assert "assignments" in out
    assert "hours_estimate" in out
    assert "warnings" in out

    assert isinstance(out["assignments"], dict)
    assert out["assignments"]
