import csv
import html
import io
import json
import os
import re
from types import SimpleNamespace

import django
from django.http import JsonResponse
from django.test import Client
from django.test.utils import override_settings

from app.infra.shift_metadata import build_shift_metadata_overlay
from app.infra.station_metadata import build_station_metadata_overlay


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def _extract_textarea_value(body: str, name: str) -> str:
    match = re.search(
        rf'<textarea[^>]*name="{re.escape(name)}"[^>]*>(.*?)</textarea>',
        body,
        re.DOTALL,
    )
    assert match is not None
    return html.unescape(match.group(1)).strip()


def _extract_working_state_code(body: str) -> str:
    working_state = json.loads(_extract_textarea_value(body, "working_state_json") or "{}")
    rows = ((working_state.get("people_grid") or {}).get("rows") or [])
    if not rows:
        return ""
    cells = (rows[0] or {}).get("cells") or []
    if not cells:
        return ""
    return str((cells[0] or {}).get("code") or "")


def _saved_working_state(*, year_month: str, date_str: str, code: str, note: str = "") -> dict:
    return {
        "people_grid": {
            "year_month": year_month,
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": code, "note": note}],
                }
            ],
        },
        "warnings": ["SAVED_WARNING"],
        "weekly_rest_warnings": [],
    }


def _delete_workspace(year_month: str) -> None:
    from core.models import MonthlyWorkspace

    MonthlyWorkspace.objects.filter(
        tenant__name="demo_kitchen",
        year_month=year_month,
    ).delete()


def _save_workspace(*, year_month: str, leave_requests: dict, working_state: dict) -> None:
    from core.monthly_workspace_persistence import save_monthly_workspace

    save_monthly_workspace(
        tenant_name="demo_kitchen",
        year_month=year_month,
        leave_requests=leave_requests,
        working_state=working_state,
    )


def _load_workspace(year_month: str) -> dict | None:
    from core.monthly_workspace_persistence import load_monthly_workspace

    return load_monthly_workspace(
        tenant_name="demo_kitchen",
        year_month=year_month,
    )


def test_ui_monthly_get_renders():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert '<form method="post" id="monthly-form" class="grid-layout">' in body
    assert 'name="language"' not in body
    assert 'class="lang-btn"' not in body
    assert '/api/tenants/demo_kitchen/daily-runs-graph/' in body
    assert re.search(r'<textarea[^>]*name="refine_text"[^>]*>', body)
    assert "Masuda on 2026-03-12 should be OFF" in body
    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>', body)
    assert re.search(r'<button[^>]*value="apply_refine"[^>]*disabled[^>]*>\s*Apply\s*</button>', body)
    assert re.search(r'<button[^>]*value="save"[^>]*>\s*Save\s*</button>', body)
    assert 'value="load"' not in body
    assert "Save persists the current working state for this month." in body


def test_ui_monthly_get_auto_hydrates_saved_workspace_without_load_button():
    _django_setup()
    _delete_workspace("2040-04")

    _save_workspace(
        year_month="2040-04",
        leave_requests={"Spencer": ["2040-04-05"]},
        working_state=_saved_working_state(
            year_month="2040-04",
            date_str="2040-04-05",
            code="D",
            note="saved",
        ),
    )

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly?year_month=2040-04")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Restored saved workspace for 2040-04." in body
    assert 'value="load"' not in body
    assert '"code": "D"' in _extract_textarea_value(body, "working_state_json")


def test_ui_monthly_get_without_saved_workspace_does_not_auto_hydrate():
    _django_setup()
    _delete_workspace("2040-05")

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly?year_month=2040-05")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Restored saved workspace for 2040-05." not in body
    assert _extract_textarea_value(body, "working_state_json") == ""


def test_ui_monthly_save_without_working_state_shows_clear_error():
    _django_setup()
    _delete_workspace("2040-05")

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2040-05",
                "language": "en",
                "leave_requests": "{}",
                "action": "save",
            },
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Save requires a current workspace. Run Preview or Apply first." in body


def test_ui_monthly_helper_names_follow_roster_metadata_provider(monkeypatch):
    _django_setup()

    monkeypatch.setattr(
        "core.ui_views.load_monthly_roster_metadata",
        lambda tenant_name: SimpleNamespace(
            ordered_names=["DB Spencer", "DB Masuda"],
            role_by_name={"DB Spencer": "staff", "DB Masuda": "staff"},
        ),
    )

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert '<option value="DB Spencer">DB Spencer</option>' in body
    assert '<option value="DB Masuda">DB Masuda</option>' in body


def test_ui_monthly_preview_post_renders_grid():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "ja",
                "leave_requests": json.dumps({"Spencer": ["2025-11-05"]}),
                "action": "preview",
            },
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "2025-11-05" in body
    assert re.search(r'<h2[^>]*data-i18n="people_grid"[^>]*>', body)
    assert re.search(r'<h2[^>]*data-i18n="weekly_rest_warnings"[^>]*>', body)


def test_ui_monthly_preview_renders_db_backed_shift_legend(monkeypatch):
    _django_setup()
    monkeypatch.setattr(
        "app.infra.monthly_scheduling_inputs.load_shift_metadata_overlay",
        lambda **kwargs: build_shift_metadata_overlay(
            base_shift_defs=kwargs["base_shift_defs"],
            db_shift_rows=[
                {
                    "code": "A",
                    "display_name": "Morning Prep",
                    "legend_label": "Morning Prep shift",
                    "paid_hours": 7.5,
                }
            ],
        ),
    )

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Shift Legend" in body
    assert "Morning Prep shift" in body


def test_ui_monthly_post_keeps_english_labels():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'name="language"' not in body
    assert re.search(r'<button[^>]*value="download"[^>]*>\s*Export CSV\s*</button>', body)
    assert re.search(r'<h2[^>]*>\s*People Grid\s*</h2>', body)


def test_ui_monthly_explain_block_placeholder_renders_when_unavailable():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "/api/tenants/demo_kitchen/daily-runs-graph/" in body
    assert re.search(r'<div[^>]*id="explain-output"[^>]*>[\s\S]*</div>', body)


def test_ui_monthly_explain_js_has_error_fallback_message():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'const fallback = getT("explain_unavailable");' in body
    assert "explainOutput.innerHTML = '<p class=\"subtle\">' + fallback + detail + \"</p>\";" in body


def test_ui_monthly_explain_js_uses_station_labels_from_api_payload():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "const stationLabels = payload.station_labels || {};" in body
    assert "const station = formatStationLabel(item.station, item.station_label);" in body


def test_ui_monthly_explain_js_prefers_trace_shift_metadata_when_present():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "function formatPickedDetail(detail) {" in body
    assert "const pickedDetails = Array.isArray(item.picked_details) ? item.picked_details : [];" in body
    assert "const pickedSummary = formatPickedSummary(item);" in body
    assert 'summary.textContent = station + (pickedSummary ? " - " + pickedSummary : "");' in body


def test_ui_monthly_voice_input_scaffold_renders():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert re.search(r'<button[^>]*id="voice-toggle"[^>]*>', body)
    assert re.search(r'<span[^>]*id="voice-status"[^>]*data-status="idle"[^>]*>', body)
    assert re.search(r'<p[^>]*id="voice-message"[^>]*>', body)
    assert 'fetch("/api/monthly/transcribe"' in body
    assert "voice_status_transcribing" in body


def test_ui_monthly_voice_input_has_unsupported_fallback_path():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'setVoiceState("unsupported", "voice_unsupported")' in body
    assert 'startSpeechRecognitionFallback("voice_recording_unsupported_fallback")' in body
    assert 'startSpeechRecognitionFallback("voice_transcribe_failed_fallback")' in body
    assert "Transcribing audio..." in body
    assert "Voice input not supported in this browser." in body
    assert "Voice recognition failed." in body


def test_ui_monthly_voice_copy_stays_clean_for_english_only_path():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        get_resp = client.get("/ui/monthly")
        preview_resp = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )

    assert get_resp.status_code == 200
    assert preview_resp.status_code == 200

    get_body = get_resp.content.decode("utf-8")
    preview_body = preview_resp.content.decode("utf-8")

    assert re.search(r'<button[^>]*id="voice-toggle"[^>]*>\s*Voice Input\s*</button>', get_body)
    assert re.search(r'<button[^>]*id="voice-toggle"[^>]*>\s*Voice Input\s*</button>', preview_body)


def test_ui_monthly_download_post_returns_csv():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "leave_requests": "{}",
                "action": "download",
            },
        )

    assert response.status_code == 200
    assert "text/csv" in response["Content-Type"]


def test_ui_monthly_refine_preview_keeps_current_working_state_until_apply(monkeypatch):
    _django_setup()

    date_str = "2025-11-05"
    fake_preview = {
        "people_grid": {
            "year_month": "2025-11",
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": "D", "note": ""}],
                }
            ],
        },
        "warnings": [],
        "weekly_rest_warnings": [],
    }

    monkeypatch.setattr("core.api_views_monthly._build_monthly_preview", lambda _inputs: fake_preview)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        preview_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )
        preview_body = preview_response.content.decode("utf-8")
        preview_working_state = _extract_textarea_value(preview_body, "working_state_json")

        refine_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": preview_working_state,
                "refine_text": "Spencer 2025-11-05 to OFF",
                "action": "refine_preview",
            },
            follow=True,
        )

        body = refine_response.content.decode("utf-8")
        working_state_json = _extract_textarea_value(body, "working_state_json")

        assert preview_response.status_code == 200
        assert refine_response.status_code == 200
        assert working_state_json == preview_working_state
        assert "Showing a refine candidate only." in body
        download_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "refine_text": "Spencer 2025-11-05 to OFF",
                "working_state_json": working_state_json,
                "action": "download",
            },
        )

    assert download_response.status_code == 200
    rows = list(csv.reader(io.StringIO(download_response.content.decode("utf-8"))))
    header = rows[0]
    date_idx = header.index(date_str)

    spencer_row = next(r for r in rows[1:] if r and r[0] == "Spencer")
    assert spencer_row[date_idx] == "D"


def test_ui_monthly_apply_updates_export_working_state(monkeypatch):
    _django_setup()

    date_str = "2025-11-05"
    fake_preview = {
        "people_grid": {
            "year_month": "2025-11",
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": "D", "note": ""}],
                }
            ],
        },
        "warnings": [],
        "weekly_rest_warnings": [],
    }

    monkeypatch.setattr("core.api_views_monthly._build_monthly_preview", lambda _inputs: fake_preview)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        preview_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )
        preview_body = preview_response.content.decode("utf-8")
        preview_working_state = _extract_textarea_value(preview_body, "working_state_json")

        refine_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": preview_working_state,
                "refine_text": "Spencer 2025-11-05 to OFF",
                "action": "refine_preview",
            },
            follow=True,
        )
        refine_body = refine_response.content.decode("utf-8")
        refine_preview_json = _extract_textarea_value(refine_body, "refine_preview_json")

        apply_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": preview_working_state,
                "refine_preview_json": refine_preview_json,
                "refine_text": "Spencer 2025-11-05 to OFF",
                "action": "apply_refine",
            },
            follow=True,
        )

        apply_body = apply_response.content.decode("utf-8")
        applied_working_state = _extract_textarea_value(apply_body, "working_state_json")

        download_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": applied_working_state,
                "action": "download",
            },
        )

    assert preview_response.status_code == 200
    assert refine_response.status_code == 200
    assert apply_response.status_code == 200
    assert "Applied to current working state." in apply_body
    assert "This refine result is applied to the current working state used by Export CSV." in apply_body
    assert download_response.status_code == 200
    rows = list(csv.reader(io.StringIO(download_response.content.decode("utf-8"))))
    header = rows[0]
    date_idx = header.index(date_str)

    spencer_row = next(r for r in rows[1:] if r and r[0] == "Spencer")
    assert spencer_row[date_idx] == "OFF"


def test_ui_monthly_save_persists_workspace_and_next_get_auto_hydrates(monkeypatch):
    _django_setup()
    _delete_workspace("2040-06")

    date_str = "2040-06-05"
    fake_preview = {
        "people_grid": {
            "year_month": "2040-06",
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": "D", "note": ""}],
                }
            ],
        },
        "warnings": ["BASE_WARNING"],
        "weekly_rest_warnings": [],
    }

    monkeypatch.setattr("core.api_views_monthly._build_monthly_preview", lambda _inputs: fake_preview)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        preview_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2040-06",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )
        preview_body = preview_response.content.decode("utf-8")
        preview_working_state = _extract_textarea_value(preview_body, "working_state_json")

        save_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2040-06",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": preview_working_state,
                "action": "save",
            },
            follow=True,
        )
        hydrated_response = client.get("/ui/monthly?year_month=2040-06")

    assert preview_response.status_code == 200
    assert save_response.status_code == 200
    assert hydrated_response.status_code == 200

    save_body = save_response.content.decode("utf-8")
    hydrated_body = hydrated_response.content.decode("utf-8")

    assert "Saved current workspace." in save_body
    assert "Restored saved workspace for 2040-06." in hydrated_body
    assert '"code": "D"' in _extract_textarea_value(hydrated_body, "working_state_json")


def test_ui_monthly_preview_after_saved_workspace_only_changes_visible_state_until_refresh(monkeypatch):
    _django_setup()
    _delete_workspace("2040-09")

    date_str = "2040-09-01"
    _save_workspace(
        year_month="2040-09",
        leave_requests={},
        working_state=_saved_working_state(
            year_month="2040-09",
            date_str=date_str,
            code="D",
            note="saved",
        ),
    )

    fake_preview = {
        "people_grid": {
            "year_month": "2040-09",
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": "C", "note": ""}],
                }
            ],
        },
        "warnings": ["CANONICAL_WARNING"],
        "weekly_rest_warnings": [],
    }

    monkeypatch.setattr("core.api_views_monthly._build_monthly_preview", lambda _inputs: fake_preview)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        saved_response = client.get("/ui/monthly?year_month=2040-09")
        preview_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2040-09",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )
        refreshed_response = client.get("/ui/monthly?year_month=2040-09")

    assert saved_response.status_code == 200
    assert preview_response.status_code == 200
    assert refreshed_response.status_code == 200

    saved_body = saved_response.content.decode("utf-8")
    preview_body = preview_response.content.decode("utf-8")
    refreshed_body = refreshed_response.content.decode("utf-8")
    workspace = _load_workspace("2040-09")

    assert _extract_working_state_code(saved_body) == "D"
    assert preview_response.redirect_chain
    assert _extract_working_state_code(preview_body) == "C"
    assert workspace is not None
    assert workspace["working_state"]["people_grid"]["rows"][0]["cells"][0]["code"] == "D"
    assert _extract_working_state_code(refreshed_body) == "D"
    assert "Restored saved workspace for 2040-09." in refreshed_body


def test_ui_monthly_refine_after_auto_hydrate_uses_saved_working_state(monkeypatch):
    _django_setup()
    _delete_workspace("2040-07")

    date_str = "2040-07-05"
    _save_workspace(
        year_month="2040-07",
        leave_requests={},
        working_state=_saved_working_state(
            year_month="2040-07",
            date_str=date_str,
            code="D",
            note="saved",
        ),
    )

    fake_preview = {
        "people_grid": {
            "year_month": "2040-07",
            "dates": [date_str],
            "rows": [
                {
                    "name": "Spencer",
                    "role": "staff",
                    "cells": [{"code": "A", "note": ""}],
                }
            ],
        },
        "warnings": ["BASE_WARNING"],
        "weekly_rest_warnings": [],
    }

    monkeypatch.setattr("core.api_views_monthly._build_monthly_preview", lambda _inputs: fake_preview)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        get_response = client.get("/ui/monthly?year_month=2040-07")
        get_body = get_response.content.decode("utf-8")
        working_state_json = _extract_textarea_value(get_body, "working_state_json")

        refine_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2040-07",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": working_state_json,
                "refine_text": "Spencer 2040-07-05 to OFF",
                "action": "refine_preview",
            },
            follow=True,
        )

    assert get_response.status_code == 200
    assert refine_response.status_code == 200
    body = refine_response.content.decode("utf-8")
    assert "D -&gt; OFF" in body


def test_ui_monthly_export_after_auto_hydrate_uses_saved_working_state():
    _django_setup()
    _delete_workspace("2040-08")

    date_str = "2040-08-05"
    _save_workspace(
        year_month="2040-08",
        leave_requests={},
        working_state=_saved_working_state(
            year_month="2040-08",
            date_str=date_str,
            code="OFF",
            note="saved",
        ),
    )

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        get_response = client.get("/ui/monthly?year_month=2040-08")
        get_body = get_response.content.decode("utf-8")
        working_state_json = _extract_textarea_value(get_body, "working_state_json")

        download_response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2040-08",
                "language": "en",
                "leave_requests": "{}",
                "working_state_json": working_state_json,
                "action": "download",
            },
        )

    assert get_response.status_code == 200
    assert download_response.status_code == 200
    rows = list(csv.reader(io.StringIO(download_response.content.decode("utf-8"))))
    header = rows[0]
    date_idx = header.index(date_str)
    spencer_row = next(r for r in rows[1:] if r and r[0] == "Spencer")
    assert spencer_row[date_idx] == "OFF"


def test_ui_monthly_refine_preview_post_renders_diff_and_preview_grid():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "refine_text": "Spencer 2025-11-05 to OFF",
                "action": "refine_preview",
            },
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert re.search(r'<h2[^>]*data-i18n="diff_preview"[^>]*>', body)
    assert "2025-11-05" in body
    assert "refine_preview_json" in body
    assert "People Grid" in body
    assert "Showing a refine candidate only. Export CSV still uses the current working state until you Apply." in body


def test_ui_monthly_refine_preview_renders_db_station_label_in_diff(monkeypatch):
    _django_setup()
    overlay = build_station_metadata_overlay(
        base_station_codes=["gateau", "petit_four", "glaze_and_fruit", "mise_en_place"],
        db_station_rows=[
            {
                "code": "gateau",
                "display_name": "Gateau Counter",
                "is_active": True,
                "sort_order": 25,
            }
        ],
    )
    monkeypatch.setattr(
        "app.infra.monthly_scheduling_inputs.load_station_metadata_overlay",
        lambda **kwargs: overlay,
    )

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2026-02",
                "language": "en",
                "leave_requests": "{}",
                "refine_text": "2/1 Gateau Counter to Kim",
                "action": "refine_preview",
            },
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert re.search(r"Gateau Counter\s*/\s*gateau", body)


def test_ui_monthly_refine_action_copy_stays_clean_for_english_only_path():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()

        get_resp = client.get("/ui/monthly")
        preview_resp = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "leave_requests": "{}",
                "action": "preview",
            },
            follow=True,
        )

    assert get_resp.status_code == 200
    assert preview_resp.status_code == 200

    get_body = get_resp.content.decode("utf-8")
    preview_body = preview_resp.content.decode("utf-8")

    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>\s*Refine Preview\s*</button>', get_body)
    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>\s*Refine Preview\s*</button>', preview_body)

def test_ui_monthly_refine_preview_shows_fallback_parse_error(monkeypatch):
    _django_setup()

    def _fake_refine_api(_request):
        return JsonResponse(
            {
                "ok": False,
                "detail": "Unable to understand refine command",
                "parse_errors": [
                    {
                        "line": "free text",
                        "code": "llm_invalid_json",
                        "message": "Unable to understand refine command",
                    }
                ],
            },
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )

    monkeypatch.setattr("core.ui_views.api_monthly_refine_mirror", _fake_refine_api)

    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2026-02",
                "language": "en",
                "leave_requests": "{}",
                "refine_text": "free text",
                "action": "refine_preview",
            },
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Refine parse failed" in body
    assert "Unable to understand refine command" in body
