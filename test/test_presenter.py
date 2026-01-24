from app.presenter import present_run_out


def test_presenter_with_dict_schedule_and_list_warnings():
    out = {
        "schedule": {"gateau": "Kim", "petit_four": "Chung"},
        "warnings": ["no candidate for glaze_and_fruit"],
    }
    resp = present_run_out(
        date="2026-01-23",
        out=out,
        generated_at="2026-01-23T11:00:00+09:00",
    )

    assert resp["ok"] is True
    assert resp["data"]["date"] == "2026-01-23"

    # assignments 變成：station + primary_person + assignees
    assert {"station": "gateau", "primary_person": "Kim", "assignees": [{"name": "Kim"}]} in resp["data"]["assignments"]
    assert {"station": "petit_four", "primary_person": "Chung", "assignees": [{"name": "Chung"}]} in resp["data"]["assignments"]

    # warnings：string list -> list[dict]
    assert resp["data"]["warnings"][0]["message"] == "no candidate for glaze_and_fruit"
    assert resp["meta"]["generated_at"] == "2026-01-23T11:00:00+09:00"


def test_presenter_with_list_assignments_and_dict_warning():
    out = {
        "assignments": [{"station": "gateau", "person": "Kim"}],
        "warnings": [{"station": "petit_four", "missing": 1}],
    }
    resp = present_run_out(date="2026-01-23", out=out, generated_at="x")

    assert resp["data"]["assignments"] == [
        {"station": "gateau", "primary_person": "Kim", "assignees": [{"name": "Kim"}]}
    ]

    # warning dict 會被 normalize 補上 code/message（依你的 presenter 規則）
    assert resp["data"]["warnings"][0]["station"] == "petit_four"
    assert resp["data"]["warnings"][0]["code"] == "WARNING"
