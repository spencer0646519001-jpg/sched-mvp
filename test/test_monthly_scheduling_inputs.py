from dataclasses import dataclass

from app.infra import monthly_scheduling_inputs as monthly_inputs


@dataclass(frozen=True)
class FakeEngineInputs:
    shifts_list: list[dict]
    rules: dict
    calendar: dict
    people: list[dict]
    station_order: list[str]


def test_build_monthly_scheduling_inputs_prefers_db_roles_for_monthly_roster(monkeypatch):
    sentinel_engine_inputs = object()
    observed = {}

    monkeypatch.setattr(monthly_inputs, "build_inputs_from_json", lambda: sentinel_engine_inputs)
    monkeypatch.setattr(
        monthly_inputs,
        "load_workers",
        lambda: {
            "people": [
                {"name": "Spencer", "role": "employee"},
                {"name": "Kim", "role": "employee"},
            ]
        },
    )

    def fake_load_people(tenant_name: str):
        observed["tenant_name"] = tenant_name
        return [
            {"name": "Spencer", "role": "chef"},
            {"name": "Kim", "role": "staff"},
            {"name": "Masuda", "role": "staff"},
        ]

    monkeypatch.setattr(monthly_inputs, "load_people", fake_load_people)

    result = monthly_inputs.build_monthly_scheduling_inputs(
        start_date="2025-11-01",
        language="ja",
        leave_requests={"Spencer": ["2025-11-05"]},
        leave_by_date={"2025-11-05": ["Spencer"]},
        tenant_name="demo_kitchen",
    )

    assert observed["tenant_name"] == "demo_kitchen"
    assert result.engine_inputs is sentinel_engine_inputs
    assert result.ordered_names == ["Spencer", "Kim"]
    assert result.role_by_name == {
        "Spencer": "chef",
        "Kim": "staff",
    }


def test_build_monthly_scheduling_inputs_falls_back_to_json_roles_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(monthly_inputs, "build_inputs_from_json", lambda: object())
    monkeypatch.setattr(
        monthly_inputs,
        "load_workers",
        lambda: {
            "people": [
                {"name": "Spencer", "role": "employee"},
                {"name": "Funatsu", "role": "chef"},
            ]
        },
    )

    def fake_load_people(_tenant_name: str):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(monthly_inputs, "load_people", fake_load_people)

    result = monthly_inputs.build_monthly_scheduling_inputs(
        start_date="2025-11-01",
        language="ja",
        leave_requests={},
        leave_by_date={},
        tenant_name="demo_kitchen",
    )

    assert result.ordered_names == ["Spencer", "Funatsu"]
    assert result.role_by_name == {
        "Spencer": "employee",
        "Funatsu": "chef",
    }


def test_build_monthly_scheduling_inputs_overlays_db_station_skills_with_per_person_fallback(monkeypatch):
    base_engine_inputs = FakeEngineInputs(
        shifts_list=[],
        rules={},
        calendar={},
        people=[
            {"name": "Kim", "role": "employee", "station_skills": ["petit_four"], "core": True},
            {"name": "Spencer", "role": "employee", "station_skills": ["mise_en_place"], "core": True},
            {"name": "Funatsu", "role": "chef"},
        ],
        station_order=["gateau", "petit_four"],
    )

    monkeypatch.setattr(monthly_inputs, "build_inputs_from_json", lambda: base_engine_inputs)
    monkeypatch.setattr(
        monthly_inputs,
        "load_workers",
        lambda: {
            "people": [
                {"name": "Kim", "role": "employee"},
                {"name": "Spencer", "role": "employee"},
                {"name": "Funatsu", "role": "chef"},
            ]
        },
    )
    monkeypatch.setattr(
        monthly_inputs,
        "load_people",
        lambda _tenant_name: [
            {"name": "Kim", "role": "staff", "station_skills": []},
            {"name": "Spencer", "role": "staff", "station_skills": ["GATEAU", "glaze_and_fruit", "gateau"]},
            {"name": "Masuda", "role": "staff", "station_skills": ["petit_four"]},
        ],
    )

    result = monthly_inputs.build_monthly_scheduling_inputs(
        start_date="2025-11-01",
        language="ja",
        leave_requests={},
        leave_by_date={},
        tenant_name="demo_kitchen",
    )

    assert result.ordered_names == ["Kim", "Spencer", "Funatsu"]
    assert result.role_by_name == {
        "Kim": "staff",
        "Spencer": "staff",
        "Funatsu": "chef",
    }
    assert result.engine_inputs is not base_engine_inputs
    assert result.engine_inputs.station_order == ["gateau", "petit_four"]
    assert result.engine_inputs.people == [
        {"name": "Kim", "role": "employee", "station_skills": ["petit_four"], "core": True},
        {"name": "Spencer", "role": "employee", "station_skills": ["gateau", "glaze_and_fruit"], "core": True},
        {"name": "Funatsu", "role": "chef"},
    ]
