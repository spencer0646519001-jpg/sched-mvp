import json
import os

import django
from django.test import Client
from django.test.utils import override_settings

from app.generate_day import EngineInputs, greedy_assign, greedy_assign_with_inputs, pick_shift_for


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def _daily_assignments_signature(date_str: str, absent: list[str]) -> str:
    result = greedy_assign(date_str, absent)
    return json.dumps(result["assignments"], ensure_ascii=False, sort_keys=True)


def test_daily_scheduler_is_repeatable_for_same_inputs():
    signatures = {
        _daily_assignments_signature("2025-11-10", [])
        for _ in range(8)
    }

    assert len(signatures) == 1


def test_daily_scheduler_is_not_contaminated_by_monthly_preview():
    _django_setup()

    before = _daily_assignments_signature("2025-11-10", [])

    payload = {
        "year_month": "2025-11",
        "language": "en",
        "leave_requests": {},
    }

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/api/monthly/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200

    after = _daily_assignments_signature("2025-11-10", [])

    assert before == after


def test_monthly_preview_people_grid_is_repeatable_for_same_request():
    _django_setup()

    payload = {
        "year_month": "2025-11",
        "language": "en",
        "leave_requests": {
            "Spencer": ["2025-11-05"],
        },
    }

    people_grid_signatures: set[str] = set()

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        for _ in range(3):
            response = client.post(
                "/api/monthly/preview",
                data=json.dumps(payload),
                content_type="application/json",
            )

            assert response.status_code == 200
            data = json.loads(response.content.decode("utf-8"))
            people_grid_signatures.add(
                json.dumps(data["people_grid"], ensure_ascii=False, sort_keys=True)
            )

    assert len(people_grid_signatures) == 1


def test_explicit_shift_preferences_still_override_fallback_rotation():
    shift = pick_shift_for(
        {
            "name": "Spencer",
            "shift_prefs": ["C", "D"],
        },
        shifts_map={
            "A": {"code": "A"},
            "B": {"code": "B"},
            "C": {"code": "C"},
            "D": {"code": "D"},
        },
        is_holiday=False,
        date_str="2025-11-10",
    )

    assert shift == "C"


def test_no_preference_fallback_spreads_shifts_across_people_deterministically():
    inputs = EngineInputs(
        shifts_list=[
            {"code": "A", "paid_hours": 8.0},
            {"code": "B", "paid_hours": 8.0},
            {"code": "C", "paid_hours": 8.0},
            {"code": "D", "paid_hours": 8.0},
        ],
        rules={
            "stations": {"gateau": 8},
            "min_staff_weekday": 8,
            "min_staff_weekend": 8,
            "max_staff_per_day": 8,
            "allow_fallback_when_short": True,
            "require_one_chef": False,
            "stations_require_morning": {},
            "morning_shifts": ["A", "B"],
        },
        calendar={"holidays": []},
        people=[
            {"name": "Ishikawa", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Mochizuki", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Takai", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Tarutani", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Komura", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Kim", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Sera", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
            {"name": "Miyazawa", "role": "staff", "station_skills": ["gateau"], "shift_prefs": []},
        ],
        station_order=["gateau"],
    )

    out = greedy_assign_with_inputs("2025-11-10", [], inputs)
    shift_codes = {
        rec["shift"]
        for rec in out["assignments"]["gateau"]
    }

    assert len(shift_codes) > 1
