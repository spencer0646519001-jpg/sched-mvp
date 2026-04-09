import json
import os
import re
from datetime import datetime
from typing import Any


SUPPORTED_REFINE_INTENTS = {"set_shift", "replace_person", "add_person"}

OFF_SYNONYMS = {
    "off",
    "休",
    "休假",
    "休み",
}

STATION_ALIASES = {
    "gateux": "gateau",
    "petitfour": "petit_four",
    "petit-four": "petit_four",
    "glazeandfruit": "glaze_and_fruit",
    "misen": "mise_en_place",
    "mise": "mise_en_place",
    "miseenplace": "mise_en_place",
    # Domain alias often used by users.
    "oven": "gateau",
}

SYSTEM_PROMPT = """You are a strict parser for monthly schedule refine commands.
Your only job: convert a user's natural language refine request into structured JSON command(s).

Hard requirements:
- Output JSON only.
- Prefer this shape:
  {"commands":[{...}]}
- Never output final schedule grids.
- Never hallucinate people/stations/shift codes that are not in provided allowlists.
- If uncertain, output:
  {"error":{"code":"cannot_parse","message":"..."}}

Supported intents:
- set_shift      (date + person + shift)
- replace_person (date + station + target_person)
- add_person     (date + station, optional person)

Meaning rules:
- OFF synonyms include: off, 休, 休假, 休み.
- "Change X on DATE to D" => set_shift
- "把 DATE 的 gateau 換成 Kim" => replace_person
- "DATE oven 再補一個人" => add_person
- "Ishikawa off on 2/1" => set_shift with shift OFF

Few-shot examples (for meaning only):
Input: 讓 2/1 Ishikawa 休
Output: {"commands":[{"intent":"set_shift","date":"2/1","person":"Ishikawa","shift":"OFF"}]}

Input: 2月1號 Ishikawa 改成休假
Output: {"commands":[{"intent":"set_shift","date":"2月1號","person":"Ishikawa","shift":"OFF"}]}

Input: 幫我把 Spencer 2/1 改成 D
Output: {"commands":[{"intent":"set_shift","date":"2/1","person":"Spencer","shift":"D"}]}

Input: 把 2/1 的 gateau 換成 Kim
Output: {"commands":[{"intent":"replace_person","date":"2/1","station":"gateau","target_person":"Kim"}]}

Input: 2/1 oven 再補一個人
Output: {"commands":[{"intent":"add_person","date":"2/1","station":"oven"}]}

Input: Change Spencer on 2/1 to D
Output: {"commands":[{"intent":"set_shift","date":"2/1","person":"Spencer","shift":"D"}]}
"""

REPAIR_PROMPT = """The previous output was not usable. Re-output valid JSON only.
Rules:
- Must be one JSON object.
- Must contain either {"commands":[...]} or {"error":{...}}.
- No markdown, no prose.
"""

KEY_VALUE_COMMAND_PATTERN = re.compile(
    r"(?i)\b(intent|date|person|station|shift|target_person)\b\s*[:=]\s*([A-Za-z0-9_/\-\u4e00-\u9fff]+)"
)


def _extract_text_content(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None)
        if choices and len(choices) > 0:
            message = getattr(choices[0], "message", None)
            if message is not None:
                content = getattr(message, "content", "")
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, dict):
                            parts.append(str(item.get("text", "")))
                        else:
                            parts.append(str(getattr(item, "text", "")))
                    return "".join(parts).strip()
                return str(content or "").strip()
    except Exception:
        pass
    return ""


def _to_structured_error(code: str, message: str, *, raw_response: str = "") -> dict:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
        "raw_response": raw_response,
    }


def _strip_code_fence(text: str) -> str:
    s = str(text or "").strip()
    if not s.startswith("```"):
        return s
    s = s.strip()
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    if lines and lines[0].strip().lower() == "json":
        lines = lines[1:]
    return "\n".join(lines).strip()


def _extract_json_object_text(text: str) -> str | None:
    s = _strip_code_fence(text)
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        return s

    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _build_key_value_command(text: str) -> dict | None:
    kv = {}
    for key, value in KEY_VALUE_COMMAND_PATTERN.findall(str(text or "")):
        kv[str(key).strip().lower()] = str(value).strip()
    if not kv:
        return None
    if "intent" not in kv:
        return None
    return {
        "commands": [
            {
                "intent": kv.get("intent"),
                "date": kv.get("date"),
                "person": kv.get("person"),
                "station": kv.get("station"),
                "shift": kv.get("shift"),
                "target_person": kv.get("target_person"),
            }
        ]
    }


def _parse_model_payload(raw_response: str) -> dict | None:
    obj_text = _extract_json_object_text(raw_response)
    if obj_text:
        try:
            parsed = json.loads(obj_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    kv_payload = _build_key_value_command(raw_response)
    if kv_payload:
        return kv_payload
    return None


def _normalize_date_token(raw_date: Any, year_month: str) -> str | None:
    token = str(raw_date or "").strip()
    if not token:
        return None
    token = re.sub(r"\s+", "", token)
    token = token.replace("號", "号")

    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", token)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
        except ValueError:
            return None

    try:
        base = datetime.strptime(str(year_month), "%Y-%m")
    except Exception:
        base = datetime.today()

    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:号)?$", token)
    if m:
        try:
            return datetime(base.year, int(m.group(1)), int(m.group(2))).date().isoformat()
        except ValueError:
            return None

    m = re.match(r"^(\d{1,2})月(\d{1,2})(?:日|号)$", token)
    if m:
        try:
            return datetime(base.year, int(m.group(1)), int(m.group(2))).date().isoformat()
        except ValueError:
            return None

    return token


def _pick_known_value(raw: Any, known_values: list[str], *, lower_key: bool = True) -> str | None:
    token = str(raw or "").strip()
    if not token:
        return None
    if token in known_values:
        return token

    value_map: dict[str, str] = {}
    for item in known_values:
        key = item.lower() if lower_key else item
        value_map[key] = item
    lookup = token.lower() if lower_key else token
    return value_map.get(lookup)


def _normalize_station(raw_station: Any, known_stations: list[str]) -> str | None:
    station = _pick_known_value(raw_station, known_stations)
    if station:
        return station
    token = re.sub(r"[\s_\-]+", "", str(raw_station or "").strip().lower())
    if not token:
        return None
    alias_target = STATION_ALIASES.get(token)
    if alias_target:
        return _pick_known_value(alias_target, known_stations)
    return None


def _normalize_shift(raw_shift: Any, known_shift_codes: list[str]) -> str | None:
    token = str(raw_shift or "").strip()
    if not token:
        return None
    lowered = token.lower()
    if lowered in OFF_SYNONYMS:
        return "OFF"
    return _pick_known_value(token.upper(), [str(s).upper() for s in known_shift_codes], lower_key=False)


def _normalize_commands(
    payload: dict,
    *,
    raw_response: str,
    year_month: str,
    known_people: list[str],
    known_stations: list[str],
    known_shift_codes: list[str],
) -> dict:
    if not isinstance(payload, dict):
        return _to_structured_error("invalid_payload", "Model output is not a JSON object.", raw_response=raw_response)

    err = payload.get("error")
    if isinstance(err, dict):
        code = str(err.get("code") or "cannot_parse").strip() or "cannot_parse"
        message = str(err.get("message") or "Unable to parse refine command.").strip()
        return _to_structured_error(code, message, raw_response=raw_response)

    commands_obj = payload.get("commands")
    if commands_obj is None and payload.get("intent"):
        commands_obj = [payload]

    if not isinstance(commands_obj, list) or not commands_obj:
        return _to_structured_error("no_command", "No command found in model output.", raw_response=raw_response)

    normalized_commands: list[dict[str, Any]] = []
    for item in commands_obj:
        if not isinstance(item, dict):
            return _to_structured_error("bad_command", "Each command must be an object.", raw_response=raw_response)

        intent = str(item.get("intent") or "").strip()
        if intent not in SUPPORTED_REFINE_INTENTS:
            return _to_structured_error(
                "unsupported_intent",
                f"Unsupported intent: {intent or '<empty>'}",
                raw_response=raw_response,
            )

        normalized_date = _normalize_date_token(item.get("date"), year_month)
        normalized_person = _pick_known_value(item.get("person"), known_people)
        normalized_station = _normalize_station(item.get("station"), known_stations)
        normalized_shift = _normalize_shift(item.get("shift"), known_shift_codes)
        normalized_target = _pick_known_value(item.get("target_person"), known_people)

        command = {
            "intent": intent,
            "date": normalized_date or item.get("date"),
            "person": normalized_person or item.get("person"),
            "station": normalized_station or item.get("station"),
            "shift": normalized_shift or item.get("shift"),
            "target_person": normalized_target or item.get("target_person"),
        }
        normalized_commands.append(command)

    return {
        "ok": True,
        "commands": normalized_commands,
        "raw_response": raw_response,
    }


def _invoke_openai_chat(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
) -> tuple[str, str | None]:
    try:
        from openai import OpenAI
    except Exception as exc:
        return "", f"OpenAI SDK unavailable: {exc}"

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=messages,
        )
    except Exception as exc:
        return "", f"LLM request failed: {exc}"

    return _extract_text_content(response), None


def parse_refine_with_llm(
    *,
    refine_text: str,
    year_month: str,
    language: str,
    known_people: list[str],
    known_stations: list[str],
    known_shift_codes: list[str],
) -> dict:
    text = str(refine_text or "").strip()
    if not text:
        return _to_structured_error("empty_input", "Refine text is empty.")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _to_structured_error("llm_unavailable", "OPENAI_API_KEY is not configured.")

    model = (
        os.getenv("OPENAI_REFINE_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or "gpt-4.1-mini"
    )

    user_payload = {
        "refine_text": text,
        "year_month": year_month,
        "language": language,
        "known_people": known_people,
        "known_stations": known_stations,
        "known_shift_codes": known_shift_codes,
        "off_synonyms": sorted(OFF_SYNONYMS),
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]

    raw_response, request_error = _invoke_openai_chat(api_key=api_key, model=model, messages=messages)
    if request_error:
        return _to_structured_error("request_failed", request_error)
    if not raw_response:
        return _to_structured_error("empty_response", "LLM response is empty.")

    parsed_payload = _parse_model_payload(raw_response)
    if parsed_payload is None:
        repair_messages = [
            {"role": "system", "content": REPAIR_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "original_input": user_payload,
                        "bad_output": raw_response,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        repair_raw, repair_err = _invoke_openai_chat(api_key=api_key, model=model, messages=repair_messages)
        if repair_err:
            return _to_structured_error("request_failed", repair_err)
        parsed_payload = _parse_model_payload(repair_raw)
        if parsed_payload is None:
            return _to_structured_error("invalid_json", "LLM returned invalid JSON.", raw_response=raw_response)
        raw_response = repair_raw or raw_response

    normalized = _normalize_commands(
        parsed_payload,
        raw_response=raw_response,
        year_month=year_month,
        known_people=known_people,
        known_stations=known_stations,
        known_shift_codes=known_shift_codes,
    )
    normalized["model"] = model
    return normalized
