import io
import os
from typing import Any


DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
SUPPORTED_TRANSCRIBE_LANGUAGES = {"en"}


class AudioTranscriptionError(RuntimeError):
    """Raised when server-side audio transcription cannot be completed."""


def _normalize_language(language: str | None) -> str | None:
    value = str(language or "").strip().lower()
    if not value:
        return None
    if value not in SUPPORTED_TRANSCRIBE_LANGUAGES:
        return None
    return value


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    if isinstance(response, dict):
        raw_text = response.get("text")
        if isinstance(raw_text, str):
            return raw_text.strip()
    return ""


def transcribe_uploaded_audio(uploaded_file, *, language: str | None = None) -> str:
    if uploaded_file is None:
        raise AudioTranscriptionError("Missing audio file.")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AudioTranscriptionError("OPENAI_API_KEY is not configured.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise AudioTranscriptionError(f"OpenAI SDK unavailable: {exc}") from exc

    file_name = str(getattr(uploaded_file, "name", "") or "audio.webm")
    audio_bytes = uploaded_file.read()
    if not audio_bytes:
        raise AudioTranscriptionError("Uploaded audio is empty.")

    audio_stream = io.BytesIO(audio_bytes)
    audio_stream.name = file_name

    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "").strip() or DEFAULT_TRANSCRIBE_MODEL
    request = {
        "model": model,
        "file": audio_stream,
    }
    normalized_language = _normalize_language(language)
    if normalized_language:
        # OpenAI transcription supports optional language hints.
        request["language"] = normalized_language

    try:
        client = OpenAI(api_key=api_key)
        response = client.audio.transcriptions.create(**request)
    except Exception as exc:
        raise AudioTranscriptionError(f"Transcription request failed: {exc}") from exc

    text = _extract_text(response)
    if not text:
        raise AudioTranscriptionError("Transcription returned empty text.")
    return text
