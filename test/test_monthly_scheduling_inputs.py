from dataclasses import dataclass

from app.infra import monthly_scheduling_inputs as monthly_inputs
from app.infra.shift_metadata import build_shift_metadata_overlay
from app.infra.station_metadata import build_station_metadata_overlay


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

    monkeypatch.setattr(
        monthly_inputs,
        "resolve_engine_inputs_for_tenant",
        lambda _tenant_name: sentinel_engine_inputs,
    )
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
        language="en",
        leave_requests={"Spencer": ["2025-11-05"]},
        leave_by_date={"2025-11-05": ["Spencer"]},
        tenant_name="demo_kitchen",
    )

    assert observed["tenant_name"] == "demo_kitchen"
    assert result.engine_inputs is sentinel_engine_inputs
    assert result.ordered_names == ["Spencer", "Kim", "Masuda"]
    assert result.role_by_name == {
        "Spencer": "chef",
        "Kim": "staff",
        "Masuda": "staff",
    }


def test_build_monthly_scheduling_inputs_falls_back_to_json_roles_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(
        monthly_inputs,
        "resolve_engine_inputs_for_tenant",
        lambda _tenant_name: object(),
    )
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
        language="en",
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

    monkeypatch.setattr(
        monthly_inputs,
        "resolve_engine_inputs_for_tenant",
        lambda _tenant_name: base_engine_inputs,
    )
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
        language="en",
        leave_requests={},
        leave_by_date={},
        tenant_name="demo_kitchen",
    )

    assert result.ordered_names == ["Kim", "Spencer", "Masuda"]
    assert result.role_by_name == {
        "Kim": "staff",
        "Spencer": "staff",
        "Funatsu": "chef",
        "Masuda": "staff",
    }
    assert result.engine_inputs is not base_engine_inputs
    assert result.engine_inputs.station_order == ["gateau", "petit_four"]
    assert result.engine_inputs.people == [
        {"name": "Kim", "role": "employee", "station_skills": ["petit_four"], "core": True},
        {"name": "Spencer", "role": "employee", "station_skills": ["gateau", "glaze_and_fruit"], "core": True},
        {"name": "Funatsu", "role": "chef"},
    ]


def test_load_monthly_roster_metadata_uses_db_active_names_but_keeps_json_role_fallback(monkeypatch):
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
            {"name": "Spencer", "role": "staff"},
            {"name": "Masuda", "role": "staff"},
        ],
    )

    result = monthly_inputs.load_monthly_roster_metadata(tenant_name="demo_kitchen")

    assert result.ordered_names == ["Spencer", "Masuda"]
    assert result.role_by_name == {
        "Kim": "employee",
        "Spencer": "staff",
        "Funatsu": "chef",
        "Masuda": "staff",
    }


def test_build_monthly_scheduling_inputs_attaches_station_metadata_overlay_without_flipping_engine_order(monkeypatch):
    sentinel_overlay = build_station_metadata_overlay(
        base_station_codes=["petit_four", "gateau", "glaze_and_fruit"],
        db_station_rows=[
            {
                "code": "gateau",
                "display_name": "Gateau Counter",
                "is_active": True,
                "sort_order": 25,
            }
        ],
    )
    observed = {}
    base_engine_inputs = FakeEngineInputs(
        shifts_list=[],
        rules={"stations": {"GATEAU": 2, "petit_four": 1, "glaze_and_fruit": 1}},
        calendar={},
        people=[],
        station_order=["petit_four", "gateau"],
    )

    monkeypatch.setattr(
        monthly_inputs,
        "resolve_engine_inputs_for_tenant",
        lambda _tenant_name: base_engine_inputs,
    )
    monkeypatch.setattr(monthly_inputs, "load_workers", lambda: {"people": []})
    monkeypatch.setattr(monthly_inputs, "load_people", lambda _tenant_name: [])

    def fake_load_station_metadata_overlay(*, tenant_name: str, base_station_codes: list[str]):
        observed["tenant_name"] = tenant_name
        observed["base_station_codes"] = list(base_station_codes)
        return sentinel_overlay

    monkeypatch.setattr(monthly_inputs, "load_station_metadata_overlay", fake_load_station_metadata_overlay)

    result = monthly_inputs.build_monthly_scheduling_inputs(
        start_date="2025-11-01",
        language="en",
        leave_requests={},
        leave_by_date={},
        tenant_name="demo_kitchen",
    )

    assert observed == {
        "tenant_name": "demo_kitchen",
        "base_station_codes": ["petit_four", "gateau", "glaze_and_fruit"],
    }
    assert result.engine_inputs.station_order == ["petit_four", "gateau"]
    assert result.station_metadata is sentinel_overlay


def test_build_monthly_scheduling_inputs_attaches_shift_metadata_overlay_without_flipping_engine_shift_truth(monkeypatch):
    sentinel_overlay = build_shift_metadata_overlay(
        base_shift_defs=[
            {"code": "A", "start": "10:00", "end": "20:00", "break_minutes": 60, "paid_hours": 9.0},
            {"code": "D", "start": "14:00", "end": "23:00", "break_minutes": 60, "paid_hours": 8.0},
        ],
        db_shift_rows=[
            {
                "code": "A",
                "display_name": "Morning Prep",
                "legend_label": "Morning Prep shift",
                "paid_hours": 7.5,
            }
        ],
    )
    observed = {}
    base_engine_inputs = FakeEngineInputs(
        shifts_list=[
            {"code": "A", "start": "10:00", "end": "20:00", "break_minutes": 60, "paid_hours": 9.0},
            {"code": "D", "start": "14:00", "end": "23:00", "break_minutes": 60, "paid_hours": 8.0},
        ],
        rules={"stations": {"GATEAU": 2}},
        calendar={},
        people=[],
        station_order=["gateau"],
    )

    monkeypatch.setattr(
        monthly_inputs,
        "resolve_engine_inputs_for_tenant",
        lambda _tenant_name: base_engine_inputs,
    )
    monkeypatch.setattr(monthly_inputs, "load_workers", lambda: {"people": []})
    monkeypatch.setattr(monthly_inputs, "load_people", lambda _tenant_name: [])
    monkeypatch.setattr(
        monthly_inputs,
        "load_station_metadata_overlay",
        lambda **kwargs: build_station_metadata_overlay(base_station_codes=["gateau"], db_station_rows=[]),
    )

    def fake_load_shift_metadata_overlay(*, tenant_name: str, base_shift_defs: list[dict]):
        observed["tenant_name"] = tenant_name
        observed["base_shift_defs"] = list(base_shift_defs)
        return sentinel_overlay

    monkeypatch.setattr(monthly_inputs, "load_shift_metadata_overlay", fake_load_shift_metadata_overlay)

    result = monthly_inputs.build_monthly_scheduling_inputs(
        start_date="2025-11-01",
        language="en",
        leave_requests={},
        leave_by_date={},
        tenant_name="demo_kitchen",
    )

    assert observed["tenant_name"] == "demo_kitchen"
    assert [item["code"] for item in observed["base_shift_defs"]] == ["A", "D"]
    assert result.engine_inputs.shifts_list == base_engine_inputs.shifts_list
    assert result.shift_metadata is sentinel_overlay
