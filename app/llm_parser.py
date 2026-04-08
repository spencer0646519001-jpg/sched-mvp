# app/llm_parser.py
import json
import os
from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, Field

from app.generate_day import load_json


class PatchParseResult(BaseModel):
    intent: Literal["adjust_shift", "non_scheduling"]

    name_raw: Optional[str] = None
    name: Optional[str] = None
    name_confidence: float = 1.0

    station_raw: Optional[str] = None
    station: Optional[str] = None
    station_confidence: float = 1.0

    shift_raw: Optional[str] = None
    shift: Optional[str] = None
    shift_confidence: float = 1.0

    reasoning: Optional[str] = ""


SYSTEM_PROMPT = """
あなたはパティスリーの「シフト調整エージェント」です。
ユーザーの文章（日本語・中国語・英語）からシフト調整指示を解析し、
次の項目を JSON で返してください：

- intent: adjust_shift / non_scheduling
- name: 従業員名
- station: ステーション名
- shift: シフトコード
- confidence: 0.0〜1.0
- reasoning: 開発者向けの簡単説明

曖昧なら null。
排班と無関係なら intent = non_scheduling。
出力は JSON のみ。

# 追加ルール（重要）
- Preserve the user's original words in *_raw fields (name_raw, station_raw, shift_raw).
- If you normalize, correct, or guess a value, reduce the corresponding *_confidence below 1.0.
- If you directly match without correction, set *_confidence to 1.0.
- *_raw はユーザー入力をそのまま入れること。
"""


# ✅ Lazy init：避免 uvicorn import 時就爆炸
_LLM = None


class LLMParserUnavailable(RuntimeError):
    """Expected legacy-parser unavailability for offline/manual parity paths."""


def _non_scheduling_result(reason: str) -> Dict[str, Any]:
    return {
        "intent": "non_scheduling",
        "name_raw": None,
        "name": None,
        "name_confidence": 0.0,
        "station_raw": None,
        "station": None,
        "station_confidence": 0.0,
        "shift_raw": None,
        "shift": None,
        "shift_confidence": 0.0,
        "reasoning": reason,
    }


def _get_llm():
    global _LLM
    if _LLM is None:
        # 這裡才 import，避免沒裝 langchain_openai 時讓整個 server 起不來
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise LLMParserUnavailable("langchain-openai is not installed.") from exc

        _LLM = ChatOpenAI(model="gpt-4.1-mini", temperature=0.0)
    return _LLM


def _build_user_prompt(user_input: str, workers, stations, shifts) -> str:
    return f"""
ユーザー入力：
{user_input}

利用可能な従業員：
{json.dumps(workers, ensure_ascii=False)}

利用可能なステーション：
{json.dumps(stations, ensure_ascii=False)}

利用可能なシフト：
{json.dumps(shifts, ensure_ascii=False)}

必ず JSON のみで返してください。
"""


def _extract_text(raw: Any) -> str:
    if isinstance(raw, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in raw
        ).strip()
    return str(raw).strip()


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    text = text.lstrip("`").strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def parse_request_to_patch(user_input: str) -> Dict[str, Any]:
    workers = [p["name"] for p in load_json("workers.json")["people"]]
    rules = load_json("rules.json")
    stations = list(rules["stations"].keys())

    shifts = [s["code"] for s in load_json("shifts.json")]

    user_prompt = _build_user_prompt(user_input, workers, stations, shifts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _non_scheduling_result(
            "LLM parser unavailable: OPENAI_API_KEY is not configured."
        )

    try:
        llm = _get_llm()
    except LLMParserUnavailable as exc:
        return _non_scheduling_result(f"LLM parser unavailable: {exc}")

    from openai import APIConnectionError, APITimeoutError, AuthenticationError

    try:
        resp = llm.invoke(messages)
    except (APIConnectionError, APITimeoutError, AuthenticationError) as exc:
        return _non_scheduling_result(
            f"LLM parser unavailable: {exc.__class__.__name__}."
        )

    text = _extract_text(resp.content)
    text = _strip_code_fence(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _non_scheduling_result("JSON parse error: " + text[:200])
