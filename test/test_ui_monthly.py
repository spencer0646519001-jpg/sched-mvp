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
    assert re.search(r"<h1[^>]*>\s*月間シフト作成ワークスペース\s*</h1>", body)
    assert re.search(r"<h2[^>]*>\s*休暇申請\s*</h2>", body)
    assert re.search(r'<input[^>]*name="language"[^>]*value="ja"', body)
    assert re.search(r'<p[^>]*data-i18n="explain_unavailable_until_generated"[^>]*>\s*生成されるまで Explain は利用できません。\s*</p>', body)


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
    assert re.search(r"<h2[^>]*>\s*スタッフグリッド\s*</h2>", body)
    assert "2025-11-05" in body
    assert re.search(r"<h2[^>]*>\s*週休チェック警告\s*</h2>", body)


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
    assert re.search(r"<h2[^>]*>\s*People Grid\s*</h2>", body)


def test_ui_monthly_explain_block_placeholder_renders_when_unavailable():
    _django_setup()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.get("/ui/monthly")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "/api/tenants/demo_kitchen/daily-runs-graph/" in body
    assert re.search(r'<div[^>]*id="explain-output"[^>]*>[\s\S]*生成されるまで Explain は利用できません。[\s\S]*</div>', body)



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
