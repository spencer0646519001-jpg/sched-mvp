from app.presenter import present_api_success


def test_present_api_success_has_ok_data_meta():
    payload = present_api_success(
        data={"run_id": 123, "out": {"ok": True, "data": {}, "meta": {}}},
        meta={"engine_version": "0.1"},
        generated_at="2026-01-25T09:00:00+09:00",
    )

    assert payload["ok"] is True
    assert payload["data"]["run_id"] == 123
    assert "out" in payload["data"]
    assert payload["meta"]["engine_version"] == "0.1"
    assert payload["meta"]["generated_at"] == "2026-01-25T09:00:00+09:00"
