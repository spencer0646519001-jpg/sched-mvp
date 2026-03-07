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
    assert re.search(r'<button[^>]*value="download"[^>]*>\s*Download CSV\s*</button>', body)
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


def test_ui_monthly_voice_input_has_unsupported_fallback_path():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'setVoiceState("unsupported", "voice_unsupported")' in body
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
