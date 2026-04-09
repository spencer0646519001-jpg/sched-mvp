import json
import os

import django
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import override_settings

from core.transcribe_audio import AudioTranscriptionError


def _django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def test_monthly_transcribe_success_returns_ok_and_text(monkeypatch):
    _django_setup()
    captured = {"language": None, "name": None}

    def _fake_transcribe(uploaded_file, *, language=None):
        captured["language"] = language
        captured["name"] = uploaded_file.name
        return "Spencer 2026-03-12 OFF"

    monkeypatch.setattr("core.api_views_monthly.transcribe_uploaded_audio", _fake_transcribe)

    audio = SimpleUploadedFile("voice.webm", b"fake-audio", content_type="audio/webm")
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post("/api/monthly/transcribe", data={"audio": audio, "language": "ja"})

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data == {"ok": True, "text": "Spencer 2026-03-12 OFF"}
    assert captured["language"] == "en"
    assert captured["name"] == "voice.webm"


def test_monthly_transcribe_failure_returns_ok_false(monkeypatch):
    _django_setup()

    def _fake_transcribe(_uploaded_file, *, language=None):
        raise AudioTranscriptionError(f"transcribe failed ({language})")

    monkeypatch.setattr("core.api_views_monthly.transcribe_uploaded_audio", _fake_transcribe)

    audio = SimpleUploadedFile("voice.webm", b"fake-audio", content_type="audio/webm")
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        client = Client()
        response = client.post("/api/monthly/transcribe", data={"audio": audio, "language": "ja"})

    assert response.status_code == 502
    data = json.loads(response.content.decode("utf-8"))
    assert data["ok"] is False
    assert "transcribe failed (en)" in data["detail"]
