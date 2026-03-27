from app.infra import monthly_scheduling_inputs as monthly_inputs


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
