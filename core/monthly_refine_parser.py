"""Monthly refine parser and LLM fallback helpers."""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from app import generate_day as gd
from app.domain.normalize import canonical_shift, canonical_station


_REFINE_OFF_SYNONYMS = {
    "off",
    "休假",
    "休み",
}

_REFINE_STATION_ALIASES = {
    "gateau": "gateau",
    "gateux": "gateau",
    "oven": "gateau",
    "petitfour": "petit_four",
    "petit_four": "petit_four",
    "petit-four": "petit_four",
    "glazeandfruit": "glaze_and_fruit",
    "glaze_and_fruit": "glaze_and_fruit",
    "misen": "mise_en_place",
    "mise": "mise_en_place",
    "miseenplace": "mise_en_place",
    "mise_en_place": "mise_en_place",
}


def _normalize_shift_lookup_key(raw: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(raw or "")).strip().lower()


def _normalize_person_lookup_key(raw: str) -> str:
    return re.sub(r"[\s_]+", "", str(raw or "")).strip().lower()


def _normalize_station_lookup_key(raw: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(raw or "")).strip().lower()


def _extract_station_tokens_from_note(note: str) -> list[str]:
    text = str(note or "")
    tokens = re.findall(
        r"(?:station:|manual_refine:removed_from:|manual_refine:)([A-Za-z0-9_\-]+)",
        text,
        flags=re.IGNORECASE,
    )
    return [tok for tok in tokens if tok]


def _build_refine_station_lookup(station_codes: list[str], station_metadata) -> dict[str, str]:
    station_lookup: dict[str, str] = {}
    allowed_codes = {canonical_station(code) for code in station_codes if canonical_station(code)}

    if station_metadata is not None:
        overlay_lookup = getattr(station_metadata, "lookup", {}) or {}
        for key, code in overlay_lookup.items():
            canonical_code = canonical_station(code)
            if key and canonical_code in allowed_codes:
                station_lookup[key] = canonical_code

    for station in station_codes:
        code = canonical_station(station)
        key = _normalize_station_lookup_key(code)
        if code and key:
            station_lookup[key] = code

    return station_lookup


def _known_refine_stations(people_grid: dict, *, station_metadata=None) -> set[str]:
    known: set[str] = set()
    overlay_codes = list(getattr(station_metadata, "ordered_codes", []) or [])
    if overlay_codes:
        known.update(overlay_codes)
    else:
        try:
            rules = gd.load_json("rules.json") or {}
            station_need = rules.get("stations") or {}
            if isinstance(station_need, dict):
                for raw_station in station_need.keys():
                    canon = canonical_station(str(raw_station or ""))
                    if canon:
                        known.add(canon)
        except Exception:
            pass

    for row in people_grid.get("rows", []) or []:
        for cell in row.get("cells", []) or []:
            note = str((cell or {}).get("note", "") or "")
            for token in _extract_station_tokens_from_note(note):
                canon = canonical_station(token)
                if canon and canon != "off":
                    known.add(canon)

    for alias_target in _REFINE_STATION_ALIASES.values():
        known.add(alias_target)
    return known


def _build_refine_shift_lookup(shift_codes: set[str], shift_metadata) -> dict[str, str]:
    lookup: dict[str, str] = {}
    allowed_codes = {canonical_shift(code) for code in shift_codes if canonical_shift(code)}

    if shift_metadata is not None:
        overlay_lookup = getattr(shift_metadata, "lookup", {}) or {}
        for key, code in overlay_lookup.items():
            canonical_code = canonical_shift(code)
            if key and canonical_code in allowed_codes:
                lookup[key] = canonical_code

    for code in sorted(allowed_codes):
        key = _normalize_shift_lookup_key(code)
        if key:
            lookup[key] = code

    return lookup


def _known_refine_shift_codes(people_grid: dict, *, shift_metadata=None) -> set[str]:
    known: set[str] = {"OFF"}
    overlay_codes = list(getattr(shift_metadata, "ordered_codes", []) or [])
    if overlay_codes:
        known.update(canonical_shift(code) for code in overlay_codes if canonical_shift(code))

    try:
        shifts = gd.load_json("shifts.json") or []
        for item in shifts:
            if not isinstance(item, dict):
                continue
            code = canonical_shift(item.get("code"))
            if code:
                known.add(code)
    except Exception:
        pass

    for row in people_grid.get("rows", []) or []:
        for cell in row.get("cells", []) or []:
            code = canonical_shift((cell or {}).get("code"))
            if code:
                known.add(code)
    return known


def _normalize_refine_date(raw_date: str, *, anchor_year: int, anchor_month: int) -> str | None:
    token = re.sub(r"\s+", "", str(raw_date or ""))
    token = token.replace("號", "号")
    if not token:
        return None

    year: int
    month: int
    day: int

    m = re.match(r"^(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})$", token)
    if m:
        year = int(m.group("y"))
        month = int(m.group("m"))
        day = int(m.group("d"))
    else:
        m = re.match(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:号)?$", token)
        if m:
            year = anchor_year
            month = int(m.group("m"))
            day = int(m.group("d"))
        else:
            m = re.match(r"^(?P<m>\d{1,2})月(?P<d>\d{1,2})(?:日|号)$", token)
            if m:
                year = anchor_year
                month = int(m.group("m"))
                day = int(m.group("d"))
            else:
                m = re.match(r"^(?P<d>\d{1,2})(?:号|日)$", token)
                if not m:
                    return None
                year = anchor_year
                month = anchor_month
                day = int(m.group("d"))

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _normalize_refine_person(raw_person: str, person_lookup: dict[str, str]) -> str | None:
    key = _normalize_person_lookup_key(raw_person)
    if key in person_lookup:
        return person_lookup[key]
    return None


def _normalize_refine_station(raw_station: str, station_lookup: dict[str, str]) -> str | None:
    token = str(raw_station or "").strip()
    if not token:
        return None

    canon = canonical_station(token)
    canon_key = _normalize_station_lookup_key(canon)
    if canon_key in station_lookup:
        return station_lookup[canon_key]

    key = _normalize_station_lookup_key(token)
    alias_target = _REFINE_STATION_ALIASES.get(key)
    if alias_target:
        alias_key = _normalize_station_lookup_key(alias_target)
        if alias_key in station_lookup:
            return station_lookup[alias_key]
    if key in station_lookup:
        return station_lookup[key]
    return None


def _normalize_refine_shift(raw_shift: str, shift_codes: set[str], *, shift_metadata=None) -> str | None:
    token = str(raw_shift or "").strip()
    if not token:
        return None

    lowered = token.lower()
    if lowered in _REFINE_OFF_SYNONYMS:
        return "OFF"

    canon = canonical_shift(token)
    if canon in shift_codes:
        return canon

    lookup = _build_refine_shift_lookup(shift_codes, shift_metadata)
    key = _normalize_shift_lookup_key(token)
    if key in lookup:
        return lookup[key]
    return None


def _refine_parse_error(line: str, code: str, message: str) -> dict:
    return {
        "line": line,
        "code": code,
        "message": message,
    }


_REFINE_LANGUAGES = {"en"}

_REFINE_PARSE_I18N = {
    "ja": {
        "parse_failed": "調整指令を理解できませんでした",
        "invalid_date": "日付を認識できません",
        "date_not_in_month": "日付が対象月に含まれていません",
        "person_not_found": "人名が見つかりません",
        "station_not_found": "站位が見つかりません",
        "shift_not_found": "シフトコードが見つかりません",
        "unparsed_command": "調整指令の形式を認識できません",
        "llm_unavailable": "LLM fallback は現在利用できません",
        "llm_request_failed": "LLM へのリクエストに失敗しました",
        "llm_invalid_json": "LLM の応答 JSON が不正です",
        "llm_empty_response": "LLM の応答が空です",
        "llm_no_command": "LLM が有効な command を返しませんでした",
        "llm_bad_command": "LLM command の形式が不正です",
        "llm_unsupported_intent": "LLM intent が未対応です",
        "llm_cannot_parse": "LLM が指令を確実に解釈できませんでした",
        "llm_unknown": "LLM fallback 解析に失敗しました",
    },
    "zh": {
        "parse_failed": "無法理解調整指令",
        "invalid_date": "無法辨識日期",
        "date_not_in_month": "日期不在目前月份",
        "person_not_found": "找不到人名",
        "station_not_found": "找不到站位",
        "shift_not_found": "找不到班別",
        "unparsed_command": "無法辨識調整指令格式",
        "llm_unavailable": "LLM fallback 目前不可用",
        "llm_request_failed": "LLM 請求失敗",
        "llm_invalid_json": "LLM 回傳的 JSON 無效",
        "llm_empty_response": "LLM 回傳為空",
        "llm_no_command": "LLM 沒有回傳有效 command",
        "llm_bad_command": "LLM command 格式無效",
        "llm_unsupported_intent": "LLM intent 不支援",
        "llm_cannot_parse": "LLM 無法可靠解析該指令",
        "llm_unknown": "LLM fallback 解析失敗",
    },
    "en": {
        "parse_failed": "Refine parse failed",
        "invalid_date": "Invalid date",
        "date_not_in_month": "Date is outside the selected month",
        "person_not_found": "Person not found",
        "station_not_found": "Station not found",
        "shift_not_found": "Shift code not found",
        "unparsed_command": "Command format not recognized",
        "llm_unavailable": "LLM fallback is unavailable",
        "llm_request_failed": "LLM request failed",
        "llm_invalid_json": "LLM returned invalid JSON",
        "llm_empty_response": "LLM returned an empty response",
        "llm_no_command": "LLM did not return a valid command",
        "llm_bad_command": "LLM command format is invalid",
        "llm_unsupported_intent": "LLM intent is not supported",
        "llm_cannot_parse": "LLM could not parse this refine instruction reliably",
        "llm_unknown": "LLM fallback parse failed",
    },
}

_LLM_ERROR_CODE_TO_PARSE_CODE = {
    "llm_unavailable": "llm_unavailable",
    "request_failed": "llm_request_failed",
    "invalid_json": "llm_invalid_json",
    "empty_response": "llm_empty_response",
    "no_command": "llm_no_command",
    "bad_command": "llm_bad_command",
    "unsupported_intent": "llm_unsupported_intent",
    "cannot_parse": "llm_cannot_parse",
}


def _normalize_refine_language(language: str) -> str:
    return "en"


def _refine_error_message(language: str, code: str) -> str:
    table = _REFINE_PARSE_I18N["en"]
    return table.get(code) or table.get("parse_failed") or "Refine parse failed"


def _localize_parse_errors(parse_errors: list[dict], language: str) -> list[dict]:
    localized: list[dict] = []
    for item in parse_errors:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        cloned = dict(item)
        if code:
            cloned["message"] = _refine_error_message(language, code)
        elif not cloned.get("message"):
            cloned["message"] = _refine_error_message(language, "parse_failed")
        localized.append(cloned)
    return localized


def _build_refine_detail(parse_errors: list[dict], *, language: str) -> str:
    base = _refine_error_message(language, "parse_failed")
    readable = [
        str(item.get("message", "")).strip()
        for item in (parse_errors or [])
        if isinstance(item, dict) and str(item.get("message", "")).strip()
    ]
    if readable:
        return f"{base}: {'; '.join(readable[:3])}"
    return base


def _parse_refine_text(
    refine_text: str,
    *,
    start_date: str,
    people_grid: dict,
    station_metadata=None,
    shift_metadata=None,
) -> tuple[list[dict], list[str], list[dict]]:
    text = str(refine_text or "").strip()
    if not text:
        return [], ["REFINE_TEXT_EMPTY"], []

    try:
        anchor = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        anchor = date.today()

    valid_dates = set((people_grid.get("dates") or []))
    person_lookup: dict[str, str] = {}
    for row in people_grid.get("rows", []) or []:
        name = str((row or {}).get("name", "") or "").strip()
        if not name:
            continue
        person_lookup[_normalize_person_lookup_key(name)] = name

    known_stations = sorted(_known_refine_stations(people_grid, station_metadata=station_metadata))
    station_lookup = _build_refine_station_lookup(known_stations, station_metadata)
    shift_codes = _known_refine_shift_codes(people_grid, shift_metadata=shift_metadata)

    lines = [line.strip() for line in re.split(r"[\r\n;]+", text) if line.strip()]
    ops: list[dict] = []
    warnings: list[str] = []
    parse_errors: list[dict] = []

    date_expr = r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}/\d{1,2}(?:[号號])?|\d{1,2}月\d{1,2}日|\d{1,2}[号號])"

    for line in lines:
        normalized_line = re.sub(r"\s+", " ", line).strip()

        def parse_date_or_error(raw_date: str) -> tuple[str | None, dict | None]:
            normalized_date = _normalize_refine_date(
                raw_date,
                anchor_year=anchor.year,
                anchor_month=anchor.month,
            )
            if not normalized_date:
                return None, _refine_parse_error(line, "invalid_date", f"無法辨識日期: {raw_date}")
            if valid_dates and normalized_date not in valid_dates:
                return None, _refine_parse_error(line, "date_not_in_month", f"日期不在目前月份: {normalized_date}")
            return normalized_date, None

        m = re.match(
            rf"^(?P<person>[A-Za-z][A-Za-z0-9_\- ]*)\s+(?P<date>{date_expr})\s*(?:改成|變成|变成|to)\s*(?P<target>\S+)$",
            normalized_line,
            re.IGNORECASE,
        ) or re.match(
            rf"^(?P<person>[A-Za-z][A-Za-z0-9_\- ]*)\s+(?P<date>{date_expr})\s+(?P<target>\S+)$",
            normalized_line,
            re.IGNORECASE,
        )
        if m:
            person = _normalize_refine_person(m.group("person"), person_lookup)
            if not person:
                parse_errors.append(
                    _refine_parse_error(line, "person_not_found", f"找不到人名: {m.group('person').strip()}")
                )
                warnings.append(f"REFINE_PARSE_ERROR:person_not_found:{line}")
                continue

            date_str, date_err = parse_date_or_error(m.group("date"))
            if date_err:
                parse_errors.append(date_err)
                warnings.append(f"REFINE_PARSE_ERROR:{date_err['code']}:{line}")
                continue

            target_raw = str(m.group("target") or "").strip().rstrip("。.,，")
            shift_or_off = _normalize_refine_shift(target_raw, shift_codes, shift_metadata=shift_metadata)
            if not shift_or_off:
                parse_errors.append(
                    _refine_parse_error(line, "shift_not_found", f"找不到班別: {target_raw}")
                )
                warnings.append(f"REFINE_PARSE_ERROR:shift_not_found:{line}")
                continue

            if shift_or_off == "OFF":
                ops.append({"type": "set_off", "person": person, "date": date_str})
            else:
                ops.append({"type": "set_shift", "person": person, "date": date_str, "shift": shift_or_off})
            continue

        m = re.match(
            rf"^(?P<date>{date_expr})\s*(?P<station>[A-Za-z][A-Za-z0-9_\- ]*)\s*(?:改成|換成|换成|to)\s*(?P<person>[A-Za-z][A-Za-z0-9_\- ]*)$",
            normalized_line,
            re.IGNORECASE,
        ) or re.match(
            rf"^把\s*(?P<date>{date_expr})\s*的\s*(?P<station>[A-Za-z][A-Za-z0-9_\- ]*)\s*(?:改成|換成|换成|to)\s*(?P<person>[A-Za-z][A-Za-z0-9_\- ]*)$",
            normalized_line,
            re.IGNORECASE,
        )
        if m:
            date_str, date_err = parse_date_or_error(m.group("date"))
            if date_err:
                parse_errors.append(date_err)
                warnings.append(f"REFINE_PARSE_ERROR:{date_err['code']}:{line}")
                continue

            station = _normalize_refine_station(m.group("station"), station_lookup)
            if not station:
                parse_errors.append(
                    _refine_parse_error(line, "station_not_found", f"找不到站位: {m.group('station').strip()}")
                )
                warnings.append(f"REFINE_PARSE_ERROR:station_not_found:{line}")
                continue

            new_person = _normalize_refine_person(m.group("person"), person_lookup)
            if not new_person:
                parse_errors.append(
                    _refine_parse_error(line, "person_not_found", f"找不到人名: {m.group('person').strip()}")
                )
                warnings.append(f"REFINE_PARSE_ERROR:person_not_found:{line}")
                continue

            ops.append(
                {
                    "type": "replace_station",
                    "date": date_str,
                    "station": station,
                    "new_person": new_person,
                }
            )
            continue

        m = re.match(
            rf"^(?P<date>{date_expr})\s*(?P<station>[A-Za-z][A-Za-z0-9_\- ]*)\s*(?:多補一個人|增加一個人|增補一個人|多补一个人|增加一个人)(?:\s*(?:由|給|给|to)\s*(?P<person>[A-Za-z][A-Za-z0-9_\- ]*))?$",
            normalized_line,
            re.IGNORECASE,
        ) or re.match(
            rf"^(?P<date>{date_expr})\s*(?:多補一個人|增加一個人|增補一個人|多补一个人|增加一个人)\s*(?:到|to)\s*(?P<station>[A-Za-z][A-Za-z0-9_\- ]*)(?:\s*(?:由|給|给|to)\s*(?P<person>[A-Za-z][A-Za-z0-9_\- ]*))?$",
            normalized_line,
            re.IGNORECASE,
        )
        if m:
            date_str, date_err = parse_date_or_error(m.group("date"))
            if date_err:
                parse_errors.append(date_err)
                warnings.append(f"REFINE_PARSE_ERROR:{date_err['code']}:{line}")
                continue

            station = _normalize_refine_station(m.group("station"), station_lookup)
            if not station:
                parse_errors.append(
                    _refine_parse_error(line, "station_not_found", f"找不到站位: {m.group('station').strip()}")
                )
                warnings.append(f"REFINE_PARSE_ERROR:station_not_found:{line}")
                continue

            person = None
            raw_person = (m.group("person") or "").strip()
            if raw_person:
                person = _normalize_refine_person(raw_person, person_lookup)
                if not person:
                    parse_errors.append(
                        _refine_parse_error(line, "person_not_found", f"找不到人名: {raw_person}")
                    )
                    warnings.append(f"REFINE_PARSE_ERROR:person_not_found:{line}")
                    continue

            ops.append(
                {
                    "type": "add_station",
                    "date": date_str,
                    "station": station,
                    "person": person,
                }
            )
            continue

        date_match = re.search(date_expr, normalized_line)
        if not date_match:
            error = _refine_parse_error(line, "invalid_date", "無法辨識日期")
        else:
            parsed_date = _normalize_refine_date(
                date_match.group(0),
                anchor_year=anchor.year,
                anchor_month=anchor.month,
            )
            if not parsed_date:
                error = _refine_parse_error(line, "invalid_date", f"無法辨識日期: {date_match.group(0)}")
            elif valid_dates and parsed_date not in valid_dates:
                error = _refine_parse_error(line, "date_not_in_month", f"日期不在目前月份: {parsed_date}")
            else:
                error = _refine_parse_error(line, "unparsed_command", "無法辨識指令，請使用調班/換人/補人的格式")
        parse_errors.append(error)
        warnings.append(f"REFINE_PARSE_ERROR:{error['code']}:{line}")

    return ops, warnings, parse_errors


def _known_refine_people(people_grid: dict) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in people_grid.get("rows", []) or []:
        name = str((row or {}).get("name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _build_refine_lookup_context(*, start_date: str, people_grid: dict, station_metadata=None, shift_metadata=None) -> dict:
    try:
        anchor = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        anchor = date.today()

    valid_dates = set((people_grid.get("dates") or []))
    person_lookup: dict[str, str] = {}
    for row in people_grid.get("rows", []) or []:
        name = str((row or {}).get("name", "") or "").strip()
        if not name:
            continue
        person_lookup[_normalize_person_lookup_key(name)] = name

    known_stations = sorted(_known_refine_stations(people_grid, station_metadata=station_metadata))
    station_lookup = _build_refine_station_lookup(known_stations, station_metadata)

    return {
        "anchor": anchor,
        "valid_dates": valid_dates,
        "person_lookup": person_lookup,
        "station_lookup": station_lookup,
        "shift_codes": _known_refine_shift_codes(people_grid, shift_metadata=shift_metadata),
        "shift_metadata": shift_metadata,
    }


def _llm_error_to_parse_error(*, line: str, error: dict, language: str) -> dict:
    raw_code = str((error or {}).get("code") or "").strip()
    mapped = _LLM_ERROR_CODE_TO_PARSE_CODE.get(raw_code)
    code = mapped or ("llm_" + raw_code if raw_code else "llm_unknown")
    message = _refine_error_message(language, code)
    return _refine_parse_error(line, code, message)


def _extract_commands_from_text(raw: str) -> list[dict]:
    text = str(raw or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        commands = parsed.get("commands")
        if isinstance(commands, list):
            return [item for item in commands if isinstance(item, dict)]
        if parsed.get("intent"):
            return [parsed]

    kv_pairs = re.findall(
        r"(?i)\b(intent|date|person|station|shift|target_person)\b\s*[:=]\s*([A-Za-z0-9_/\-\u4e00-\u9fff]+)",
        text,
    )
    if not kv_pairs:
        return []

    command: dict[str, str] = {}
    for key, value in kv_pairs:
        command[str(key).strip().lower()] = str(value).strip()
    if not command.get("intent"):
        return []
    return [command]


def _extract_llm_commands(llm_result: dict) -> list[dict]:
    if not isinstance(llm_result, dict):
        return []
    commands = llm_result.get("commands")
    if isinstance(commands, list):
        return [item for item in commands if isinstance(item, dict)]

    for key in ("raw_response", "text", "content"):
        candidate = llm_result.get(key)
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        parsed = _extract_commands_from_text(candidate)
        if parsed:
            return parsed
    return []


def _llm_command_to_operation(
    *,
    line: str,
    command: dict,
    context: dict,
    language: str,
) -> tuple[dict | None, dict | None]:
    if not isinstance(command, dict):
        return None, _refine_parse_error(line, "llm_bad_command", _refine_error_message(language, "llm_bad_command"))

    intent = str(command.get("intent") or "").strip()
    if intent not in {"set_shift", "replace_person", "add_person"}:
        return None, _refine_parse_error(
            line,
            "llm_unsupported_intent",
            _refine_error_message(language, "llm_unsupported_intent"),
        )

    anchor = context["anchor"]
    valid_dates = context["valid_dates"]
    person_lookup = context["person_lookup"]
    station_lookup = context["station_lookup"]
    shift_codes = context["shift_codes"]
    shift_metadata = context.get("shift_metadata")

    raw_date = str(command.get("date") or "").strip()
    normalized_date = _normalize_refine_date(raw_date, anchor_year=anchor.year, anchor_month=anchor.month)
    if not normalized_date:
        return None, _refine_parse_error(line, "invalid_date", _refine_error_message(language, "invalid_date"))
    if valid_dates and normalized_date not in valid_dates:
        return None, _refine_parse_error(
            line,
            "date_not_in_month",
            _refine_error_message(language, "date_not_in_month"),
        )

    if intent == "set_shift":
        person = _normalize_refine_person(str(command.get("person") or ""), person_lookup)
        if not person:
            return None, _refine_parse_error(
                line,
                "person_not_found",
                _refine_error_message(language, "person_not_found"),
            )
        shift = _normalize_refine_shift(
            str(command.get("shift") or ""),
            shift_codes,
            shift_metadata=shift_metadata,
        )
        if not shift:
            return None, _refine_parse_error(
                line,
                "shift_not_found",
                _refine_error_message(language, "shift_not_found"),
            )
        if shift == "OFF":
            return {"type": "set_off", "person": person, "date": normalized_date}, None
        return {"type": "set_shift", "person": person, "date": normalized_date, "shift": shift}, None

    station = _normalize_refine_station(str(command.get("station") or ""), station_lookup)
    if not station:
        return None, _refine_parse_error(
            line,
            "station_not_found",
            _refine_error_message(language, "station_not_found"),
        )

    if intent == "replace_person":
        raw_new_person = str(command.get("target_person") or command.get("person") or "").strip()
        new_person = _normalize_refine_person(raw_new_person, person_lookup)
        if not new_person:
            return None, _refine_parse_error(
                line,
                "person_not_found",
                _refine_error_message(language, "person_not_found"),
            )
        return {
            "type": "replace_station",
            "date": normalized_date,
            "station": station,
            "new_person": new_person,
        }, None

    raw_person = str(command.get("person") or command.get("target_person") or "").strip()
    if raw_person:
        person = _normalize_refine_person(raw_person, person_lookup)
        if not person:
            return None, _refine_parse_error(
                line,
                "person_not_found",
                _refine_error_message(language, "person_not_found"),
            )
    else:
        person = None

    return {
        "type": "add_station",
        "date": normalized_date,
        "station": station,
        "person": person,
    }, None


def _parse_refine_text_with_llm_fallback(
    *,
    refine_text: str,
    year_month: str,
    start_date: str,
    language: str,
    people_grid: dict,
    station_metadata=None,
    shift_metadata=None,
    parse_refine_with_llm_hook,
) -> tuple[list[dict], list[str], list[dict], dict]:
    warnings: list[str] = ["REFINE_LLM_FALLBACK_ATTEMPTED"]
    parse_errors: list[dict] = []
    explain: dict = {"parser": "llm_fallback_v1", "ops_count": 0, "fallback_used": True}
    known_stations = sorted(_known_refine_stations(people_grid, station_metadata=station_metadata))

    llm_result = parse_refine_with_llm_hook(
        refine_text=refine_text,
        year_month=year_month,
        language=language,
        known_people=_known_refine_people(people_grid),
        known_stations=known_stations,
        known_shift_codes=sorted(_known_refine_shift_codes(people_grid, shift_metadata=shift_metadata)),
    )

    if not isinstance(llm_result, dict) or not llm_result.get("ok"):
        error = llm_result.get("error") if isinstance(llm_result, dict) else {}
        parse_errors.append(_llm_error_to_parse_error(line=refine_text, error=error if isinstance(error, dict) else {}, language=language))
        warnings.append("REFINE_LLM_FALLBACK_FAILED")
        return [], warnings, parse_errors, explain

    commands = _extract_llm_commands(llm_result)
    if not commands:
        parse_errors.append(
            _refine_parse_error(refine_text, "llm_no_command", _refine_error_message(language, "llm_no_command"))
        )
        warnings.append("REFINE_LLM_FALLBACK_FAILED")
        return [], warnings, parse_errors, explain

    context = _build_refine_lookup_context(
        start_date=start_date,
        people_grid=people_grid,
        station_metadata=station_metadata,
        shift_metadata=shift_metadata,
    )
    ops: list[dict] = []
    for command in commands:
        op, err = _llm_command_to_operation(line=refine_text, command=command, context=context, language=language)
        if err:
            parse_errors.append(err)
            continue
        if op:
            ops.append(op)

    if not ops:
        warnings.append("REFINE_LLM_FALLBACK_FAILED")
    else:
        warnings.append("REFINE_LLM_FALLBACK_USED")
    explain["ops_count"] = len(ops)
    return ops, warnings, parse_errors, explain
