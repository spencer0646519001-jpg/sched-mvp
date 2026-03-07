import json
import os
import re

import django
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
