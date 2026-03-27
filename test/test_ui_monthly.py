import csv
import html
import io
import json
import os
import re

import django
from django.http import JsonResponse
from django.test import Client
from django.test.utils import override_settings


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


def test_ui_monthly_get_renders():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert '<form method="post" id="monthly-form" class="grid-layout">' in body
    assert re.search(r'<input[^>]*name="language"[^>]*value="ja"', body)
    assert '/api/tenants/demo_kitchen/daily-runs-graph/' in body
    assert re.search(r'<textarea[^>]*name="refine_text"[^>]*>', body)
    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>', body)
    assert re.search(r'<button[^>]*value="apply_refine"[^>]*disabled[^>]*>\s*Apply\s*</button>', body)
    assert re.search(r'<button[^>]*type="button"[^>]*data-i18n="save_label"[^>]*disabled[^>]*>\s*Save\s*</button>', body)
    assert "Save is disabled until monthly persistence is implemented." in body


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
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "2025-11-05" in body
    assert re.search(r'<h2[^>]*data-i18n="people_grid"[^>]*>', body)
    assert re.search(r'<h2[^>]*data-i18n="weekly_rest_warnings"[^>]*>', body)


def test_ui_monthly_language_switch_label_on_post():
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
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert re.search(r'<input[^>]*name="language"[^>]*value="en"', body)
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
    assert 'const fallback = getT(currentLanguage, "explain_unavailable");' in body
    assert "explainOutput.innerHTML = '<p class=\"subtle\">' + fallback + detail + \"</p>\";" in body


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


def test_ui_monthly_voice_i18n_switches_ja_zh_en():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        ja_resp = client.get("/ui/monthly")
        zh_resp = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "zh",
                "leave_requests": "{}",
                "action": "preview",
            },
        )
        en_resp = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
        )

    assert ja_resp.status_code == 200
    assert zh_resp.status_code == 200
    assert en_resp.status_code == 200

    ja_body = ja_resp.content.decode("utf-8")
    zh_body = zh_resp.content.decode("utf-8")
    en_body = en_resp.content.decode("utf-8")

    assert re.search(r'<button[^>]*id="voice-toggle"[^>]*>\s*音声入力\s*</button>', ja_body)
    assert re.search(r'<button[^>]*id="voice-toggle"[^>]*>\s*語音輸入\s*</button>', zh_body)
    assert re.search(r'<button[^>]*id="voice-toggle"[^>]*>\s*Voice Input\s*</button>', en_body)


def test_ui_monthly_download_post_returns_csv():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "ja",
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
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert re.search(r'<h2[^>]*data-i18n="diff_preview"[^>]*>', body)
    assert "2025-11-05" in body
    assert "refine_preview_json" in body
    assert "People Grid" in body
    assert "Showing a refine candidate only. Export CSV still uses the current working state until you Apply." in body


def test_ui_monthly_refine_action_i18n_switches_between_ja_zh_en():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()

        ja_resp = client.get("/ui/monthly")
        en_resp = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "en",
                "leave_requests": "{}",
                "action": "preview",
            },
        )
        zh_resp = client.post(
            "/ui/monthly",
            data={
                "year_month": "2025-11",
                "language": "zh",
                "leave_requests": "{}",
                "action": "preview",
            },
        )

    assert ja_resp.status_code == 200
    assert en_resp.status_code == 200
    assert zh_resp.status_code == 200

    ja_body = ja_resp.content.decode("utf-8")
    en_body = en_resp.content.decode("utf-8")
    zh_body = zh_resp.content.decode("utf-8")

    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>\s*調整プレビュー\s*</button>', ja_body)
    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>\s*Refine Preview\s*</button>', en_body)
    assert re.search(r'<button[^>]*value="refine_preview"[^>]*>\s*調整預覽\s*</button>', zh_body)

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
        )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Refine parse failed" in body
    assert "Unable to understand refine command" in body
