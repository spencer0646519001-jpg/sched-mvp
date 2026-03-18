"""
Canonical Django HTTP layer for the repository's current runtime.

Notes for reviewers:
- Django is the canonical backend runtime today.
- This module contains both canonical Django endpoints and migration-era mirror
  endpoints that preserve older route shapes during the FastAPI -> Django move.
- The shared scheduling engine still loads its working inputs from `data/*.json`
  on the current daily/graph/weekly/monthly paths.
- Database models are real and used for persistence, but the monthly demo flow
  is still request-scoped preview/refine/export rather than DB-backed planning.
"""

# core/api_views.py
import json
import csv
import io
import re
from datetime import date, timedelta, datetime

from django.http import JsonResponse
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from dateutil import parser as dtparser
from core.presenters.daily_run_presenter import present_create_daily_run_success

from core.models import ScheduleRun
from app.month_service import run_daily_schedule
from app.run_service import build_out_from_run
from app.presenter import (
    present_run_out,
    present_api_success,
    present_api_error,
)
from app import generate_day as gd
from app.domain.normalize import canonical_shift, canonical_station
from app.plan_service import (
    create_plan,
    patch_preview,
    patch_apply,
    get_plan,
    list_all_plans,
    delete_plan,
)
from app.generate_week import generate_week, summarize_week
from app.month_service import build_month
from core.refine_llm import parse_refine_with_llm
from core.transcribe_audio import AudioTranscriptionError, transcribe_uploaded_audio
from core.shift_defs import (
    ShiftDefsInvalid,
    ShiftDefsNotFound,
    build_shift_legend,
    load_shift_defs,
)


@require_http_methods(["GET"])
def root_healthcheck(request):
    return JsonResponse({"status": "ok"}, json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def generate_day_api_mirror(request, date: str):
    absent = request.GET.get("absent", "")
    absent_list = [x.strip() for x in absent.split(",") if x.strip()] if absent else []

    try:
        result = gd.greedy_assign(date, absent_list)
        return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)
    except Exception as e:
        return JsonResponse({"detail": str(e)}, json_dumps_params={"ensure_ascii": False}, status=500)


def _parse_request_payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}"), None
    except json.JSONDecodeError:
        payload_err = present_api_error(
            code="invalid_json",
            message="Invalid JSON body",
        )
        return None, payload_err


def _validate_daily_run_payload(payload, *, include_absent_type: bool):
    date_str = payload.get("date")
    if not date_str:
        payload_err = present_api_error(
            code="missing_date",
            message="Missing 'date' in body",
        )
        return None, None, payload_err

    absent = payload.get("absent") or []
    if not isinstance(absent, list):
        details = {"absent_type": type(absent).__name__} if include_absent_type else None
        payload_err = present_api_error(
            code="invalid_absent",
            message="'absent' must be a list",
            details=details,
        )
        return None, None, payload_err

    return date_str, absent, None


@csrf_exempt
@require_http_methods(["POST"])
def create_daily_run(request, tenant_name: str):
    # 1) parse JSON
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 2) validate
    date_str, absent, payload_err = _validate_daily_run_payload(
        payload,
        include_absent_type=True,
    )
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 3) run engine + save DB
    run = run_daily_schedule(tenant_name, date_str, absent=absent)

    # 4) build out (raw)
    out = build_out_from_run(run)

    # ✅ 5) delegate presentation
    payload_ok = present_create_daily_run_success(
        run_id=run.id,
        date_str=date_str,
        out=out,
    )

    return JsonResponse(payload_ok, json_dumps_params={"ensure_ascii": False}, status=201)

@require_http_methods(["GET"])
def get_run_out(request, run_id: int):
    try:
        run = ScheduleRun.objects.get(id=run_id)
    except ScheduleRun.DoesNotExist:
        payload_err = present_api_error(
            code="run_not_found",
            message="Run not found",
            details={"run_id": run_id},
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=404)

    out = build_out_from_run(run)
    presented = present_run_out(date=str(run.start_date), out=out)

    payload_ok = present_api_success(
        data={"run_id": run.id, "out": presented},
        meta={"engine_version": "0.1"},
    )
    return JsonResponse(payload_ok, json_dumps_params={"ensure_ascii": False}, status=200)



@require_http_methods(["GET"])
def health(request):
    payload_ok = present_api_success(
        data={"status": "ok"},
        meta={"engine_version": "0.1"},
    )
    return JsonResponse(payload_ok, json_dumps_params={"ensure_ascii": False}, status=200)
@csrf_exempt
@require_http_methods(["POST"])
def create_daily_run_graph(request, tenant_name: str):
    """
    POST body:
    {
      "date": "2026-01-06",
      "absent": ["Kim", "Spencer"]
    }

    Same payload contract as create_daily_run, but backed by LangGraph.
    """
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    date_str, absent, payload_err = _validate_daily_run_payload(
        payload,
        include_absent_type=False,
    )
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)
    language = str(payload.get("language") or "en").strip().lower()
    if language not in {"ja", "en", "zh"}:
        language = "en"

    try:
        from app.langgraph_flow import run_daily_schedule_graph
    except ModuleNotFoundError as e:
        if "langgraph" in str(e):
            return JsonResponse(
                {
                    "ok": False,
                    "detail": "langgraph not installed",
                },
                status=501,
                json_dumps_params={"ensure_ascii": False},
            )
        raise

    try:
        result = run_daily_schedule_graph(
            tenant_name=tenant_name,
            date_str=date_str,
            absent=absent,
            language=language,
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "detail": str(exc)},
            json_dumps_params={"ensure_ascii": False},
            status=500,
        )

    data = result.get("data") or {}
    compat = result.get("compat") or {}

    out = data.get("out") or compat.get("out_engine")
    trace = data.get("decision_trace") or compat.get("decision_trace") or []
    explanations = data.get("explanations") or compat.get("explanations") or {}
    metrics = data.get("metrics") or compat.get("metrics") or {}

    if out is None:
        return JsonResponse(
            {"ok": False, "detail": "missing graph output"},
            json_dumps_params={"ensure_ascii": False},
            status=500,
        )

    out["explanations"] = explanations
    presented = present_run_out(date=date_str, out=out)

    stations_count = len(explanations) if isinstance(explanations, dict) else 0
    if language == "ja":
        summary = f"{stations_count} 件の站位について説明を生成しました。"
        fallback_suffix = "fallback 使用站位: "
    elif language == "zh":
        summary = f"已為 {stations_count} 個站位產生說明。"
        fallback_suffix = "fallback 使用站位："
    else:
        summary = f"Generated explanation for {stations_count} station(s)."
        fallback_suffix = "Fallback used on "
    if isinstance(metrics, dict) and metrics.get("fallback_stations") is not None:
        count = metrics.get("fallback_stations")
        if language == "en":
            summary = summary + f" {fallback_suffix}{count} station(s)."
        else:
            summary = summary + f" {fallback_suffix}{count}"

    text_parts = []
    if isinstance(explanations, dict):
        for station, note in explanations.items():
            text_parts.append(f"[{station}]")
            text_parts.append(str(note or ""))
    text = "\n".join(text_parts).strip()

    return JsonResponse(
        {
            "ok": True,
            "date": date_str,
            "summary": summary,
            "trace": trace if isinstance(trace, list) else [],
            "text": text,
            "metrics": metrics if isinstance(metrics, dict) else {},
            "explanations": explanations if isinstance(explanations, dict) else {},
            # backward compatibility for existing clients
            "data": {
                "out": presented,
                "decision_trace": trace if isinstance(trace, list) else [],
                "explanations": explanations if isinstance(explanations, dict) else {},
                "metrics": metrics if isinstance(metrics, dict) else {},
            },
            "meta": {"engine_version": "0.1"},
        },
        json_dumps_params={"ensure_ascii": False},
        status=200,
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_plan_create_mirror(request):
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    date = payload.get("date", "2025-11-10")
    result = create_plan(date)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def api_plan_patch_preview_mirror(request):
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    plan_id = payload.get("plan_id")
    text_input = payload.get("text")
    if not plan_id:
        return JsonResponse({"detail": "MISSING_PLAN_ID"}, json_dumps_params={"ensure_ascii": False}, status=422)
    if not text_input:
        return JsonResponse({"detail": "MISSING_TEXT"}, json_dumps_params={"ensure_ascii": False}, status=422)

    result = patch_preview(plan_id, text_input)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def api_plan_patch_apply_mirror(request):
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    plan_id = payload.get("plan_id")
    text_input = payload.get("text")
    if not plan_id:
        return JsonResponse({"detail": "MISSING_PLAN_ID"}, json_dumps_params={"ensure_ascii": False}, status=422)
    if not text_input:
        return JsonResponse({"detail": "MISSING_TEXT"}, json_dumps_params={"ensure_ascii": False}, status=422)

    result = patch_apply(plan_id, text_input)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_plan_get_mirror(request):
    plan_id = request.GET.get("plan_id", "")
    if not plan_id:
        return JsonResponse(
            {"detail": "MISSING_PLAN_ID"},
            json_dumps_params={"ensure_ascii": False},
            status=422,
        )

    result = get_plan(plan_id)
    if result.get("errors") == ["PLAN_NOT_FOUND"]:
        return JsonResponse({"detail": "PLAN_NOT_FOUND"}, json_dumps_params={"ensure_ascii": False}, status=404)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_plan_list_mirror(request):
    return JsonResponse(list_all_plans(), json_dumps_params={"ensure_ascii": False}, status=200, safe=False)


@csrf_exempt
@require_http_methods(["DELETE"])
def api_plan_delete_mirror(request):
    plan_id = request.GET.get("plan_id", "")
    if not plan_id:
        return JsonResponse({"detail": "MISSING_PLAN_ID"}, json_dumps_params={"ensure_ascii": False}, status=422)

    result = delete_plan(plan_id)
    if result.get("errors") == ["PLAN_NOT_FOUND"]:
        return JsonResponse({"detail": "PLAN_NOT_FOUND"}, json_dumps_params={"ensure_ascii": False}, status=404)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_week_mirror(request):
    start_date = request.GET.get("start_date", "2025-11-10")
    days = int(request.GET.get("days", "7"))
    week_state = generate_week(start_date_str=start_date, num_days=days, prev_state=None)
    return JsonResponse(week_state["week_plan"], json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_week_summary_mirror(request):
    start_date = request.GET.get("start_date", "2025-11-10")
    days = int(request.GET.get("days", "7"))
    week_state = generate_week(start_date_str=start_date, num_days=days, prev_state=None)
    return JsonResponse(summarize_week(week_state), json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_week_csv_mirror(request):
    start_date = request.GET.get("start_date")
    days = int(request.GET.get("days", "7"))

    week_state = generate_week(start_date, num_days=days, prev_state=None)
    week_plan = week_state["week_plan"]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "station", "name", "shift", "chef_present"])

    for date_str, plan in sorted(week_plan.items()):
        chefs = ",".join(plan.get("chefs_present", []))
        assignments = plan.get("assignments", {})
        for station, recs in assignments.items():
            for rec in recs:
                writer.writerow([date_str, station, rec["name"], rec["shift"], chefs])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="week_{start_date}.csv"'
    return response


def _generate_month_state(
    start_date_str: str,
    leave_by_date: dict[str, list[str]] | None = None,
) -> dict:
    base_date = dtparser.parse(start_date_str).date()
    month_start = base_date.replace(day=1)

    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    month_end = next_month - timedelta(days=1)

    cur = month_start
    prev_state: dict | None = None
    month_plan: dict = {}
    summary_total: dict = {}

    while cur <= month_end:
        days_left = (month_end - cur).days + 1
        chunk_days = min(7, days_left)

        week_state = generate_week(
            cur.isoformat(),
            num_days=chunk_days,
            prev_state=prev_state,
            leave_by_date=leave_by_date,
        )
        month_plan.update(week_state["week_plan"])

        week_summary = summarize_week(week_state)
        for name, stats in week_summary.items():
            total = summary_total.setdefault(name, {"days": 0, "hours": 0.0})
            total["days"] += int(stats["days"])
            total["hours"] += float(stats["hours"])

        prev_state = week_state
        cur += timedelta(days=chunk_days)

    overtime: dict = {}
    for name, stats in summary_total.items():
        hrs = stats["hours"]
        status = None
        if hrs > 75:
            status = "HARD_LIMIT"
        elif hrs > 45:
            status = "WARNING"
        if status:
            overtime[name] = {"status": status, "hours": hrs}

    return {
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "plan": month_plan,
        "summary": summary_total,
        "overtime": overtime,
    }




def _validate_year_month(year_month) -> tuple[str | None, str | None]:
    if not isinstance(year_month, str) or not year_month:
        return None, "'year_month' is required (YYYY-MM)"

    try:
        month_start = datetime.strptime(year_month, "%Y-%m").date().replace(day=1)
    except ValueError:
        return None, "Invalid 'year_month' format. Expected YYYY-MM"

    return month_start.isoformat(), None


def _validate_leave_requests(leave_requests) -> tuple[dict, dict, str | None]:
    if leave_requests is None:
        leave_requests = {}

    if not isinstance(leave_requests, dict):
        return {}, {}, "'leave_requests' must be dict[str, list[str]]"

    clean_by_person: dict[str, list[str]] = {}
    by_date: dict[str, list[str]] = {}

    for person, dates in leave_requests.items():
        if not isinstance(person, str) or not isinstance(dates, list):
            return {}, {}, "'leave_requests' must be dict[str, list[str]]"

        clean_dates: list[str] = []
        for date_str in dates:
            if not isinstance(date_str, str):
                return {}, {}, "'leave_requests' must be dict[str, list[str]]"
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                return {}, {}, f"Invalid leave date format: {date_str}"
            clean_dates.append(date_str)

        dedup_dates = list(dict.fromkeys(clean_dates))
        clean_by_person[person] = dedup_dates
        for date_str in dedup_dates:
            by_date.setdefault(date_str, []).append(person)

    for date_str, names in by_date.items():
        by_date[date_str] = list(dict.fromkeys(names))

    return clean_by_person, by_date, None


def _generate_month_state_with_leave_requests(start_date_str: str, leave_by_date: dict[str, list[str]]) -> dict:
    return _generate_month_state(start_date_str, leave_by_date=leave_by_date)


def _month_dates(month_state: dict) -> list[str]:
    month_start = month_state.get("month_start")
    month_end = month_state.get("month_end")
    if not month_start or not month_end:
        return []

    cur = datetime.strptime(month_start, "%Y-%m-%d").date()
    end = datetime.strptime(month_end, "%Y-%m-%d").date()
    dates: list[str] = []
    while cur <= end:
        dates.append(cur.isoformat())
        cur += timedelta(days=1)
    return dates


def _to_grid_role(role: str) -> str:
    normalized = (role or "").strip().lower()
    if normalized == "chef":
        return "chef"
    if normalized:
        return "staff"
    return "unknown"


def _build_people_grid_and_legend(
    month_state: dict,
    ordered_names: list[str],
    role_by_name: dict[str, str],
    grid: dict[str, dict[str, dict]],
) -> tuple[dict, dict]:
    dates = _month_dates(month_state)
    year_month = (month_state.get("month_start") or "")[:7]

    rows: list[dict] = []
    used_codes: set[str] = set()
    for name in ordered_names:
        cells: list[dict] = []
        for date_str in dates:
            source = (grid.get(name) or {}).get(date_str) or {}
            code = str(source.get("code", "") or "")
            note_list = source.get("notes", [])
            if isinstance(note_list, list):
                note = " | ".join(str(x) for x in note_list if x)
            elif note_list:
                note = str(note_list)
            else:
                note = ""

            if code:
                used_codes.add(code)
            cells.append({"code": code, "note": note})

        rows.append(
            {
                "name": name,
                "role": _to_grid_role(role_by_name.get(name, "")),
                "cells": cells,
            }
        )

    legend = build_shift_legend(load_shift_defs())
    for code in sorted(used_codes):
        if code not in legend:
            legend[code] = {"label": "Shift code"}

    return {
        "year_month": year_month,
        "dates": dates,
        "rows": rows,
    }, legend



def _build_weekly_rest_warnings_from_people_grid(people_grid: dict) -> list[dict]:
    dates = people_grid.get("dates", []) or []
    rows = people_grid.get("rows", []) or []

    week_to_indices: dict[str, list[int]] = {}
    for idx, date_str in enumerate(dates):
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        week_to_indices.setdefault(week_key, []).append(idx)

    warnings: list[dict] = []
    for week_key, indices in sorted(week_to_indices.items()):
        # Avoid month-boundary false positives: only validate full 7-day ISO weeks.
        if len(indices) != 7:
            continue

        for row in rows:
            name = row.get("name")
            if not name:
                continue

            cells = row.get("cells", []) or []
            worked = 0
            for cell_idx in indices:
                if cell_idx < len(cells):
                    code = str((cells[cell_idx] or {}).get("code", "") or "").strip()
                    if code and code != "OFF":
                        worked += 1

            days_off = 7 - worked
            if days_off < 2:
                warnings.append(
                    {
                        "type": "weekly_rest",
                        "person": name,
                        "week": week_key,
                        "days_off": days_off,
                        "required": 2,
                    }
                )

    return warnings


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


def _known_refine_stations(people_grid: dict) -> set[str]:
    known: set[str] = set()
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


def _known_refine_shift_codes(people_grid: dict) -> set[str]:
    known: set[str] = {"OFF"}
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


def _normalize_refine_shift(raw_shift: str, shift_codes: set[str]) -> str | None:
    token = str(raw_shift or "").strip()
    if not token:
        return None

    lowered = token.lower()
    if lowered in _REFINE_OFF_SYNONYMS:
        return "OFF"

    canon = canonical_shift(token)
    if canon in shift_codes:
        return canon
    return None


def _refine_parse_error(line: str, code: str, message: str) -> dict:
    return {
        "line": line,
        "code": code,
        "message": message,
    }


_REFINE_LANGUAGES = {"ja", "zh", "en"}

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
    lang = str(language or "ja").strip().lower()
    if lang not in _REFINE_LANGUAGES:
        return "ja"
    return lang


def _refine_error_message(language: str, code: str) -> str:
    lang = _normalize_refine_language(language)
    table = _REFINE_PARSE_I18N.get(lang) or _REFINE_PARSE_I18N["en"]
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


def _people_grid_to_lookup(people_grid: dict) -> tuple[dict, dict, dict]:
    date_to_index = {d: i for i, d in enumerate((people_grid.get("dates") or []))}
    row_by_name: dict[str, dict] = {}
    row_by_name_folded: dict[str, dict] = {}
    for row in people_grid.get("rows", []) or []:
        name = row.get("name")
        if not isinstance(name, str) or not name:
            continue
        row_by_name[name] = row
        row_by_name_folded[_normalize_person_lookup_key(name)] = row
    return date_to_index, row_by_name, row_by_name_folded


def _ensure_refine_row(people_grid: dict, person: str) -> dict:
    for row in people_grid.get("rows", []) or []:
        if row.get("name") == person:
            return row
    dates = people_grid.get("dates") or []
    new_row = {
        "name": person,
        "role": "unknown",
        "cells": [{"code": "", "note": ""} for _ in dates],
    }
    people_grid.setdefault("rows", []).append(new_row)
    return new_row


def _resolve_person_row(people_grid: dict, person: str) -> tuple[str, dict]:
    date_to_index, row_by_name, row_by_name_folded = _people_grid_to_lookup(people_grid)
    _ = date_to_index
    if person in row_by_name:
        return person, row_by_name[person]
    lookup_key = _normalize_person_lookup_key(person)
    if lookup_key in row_by_name_folded:
        row = row_by_name_folded[lookup_key]
        return row.get("name") or person, row
    row = _ensure_refine_row(people_grid, person)
    return person, row


def _find_station_holder(people_grid: dict, date_str: str, station: str) -> tuple[str | None, dict | None]:
    date_to_index, _, _ = _people_grid_to_lookup(people_grid)
    idx = date_to_index.get(date_str)
    if idx is None:
        return None, None
    station_norm = _normalize_station_lookup_key(station)
    for row in people_grid.get("rows", []) or []:
        cells = row.get("cells") or []
        if idx >= len(cells):
            continue
        cell = cells[idx] or {}
        note = str(cell.get("note", "") or "")
        code = str(cell.get("code", "") or "")
        station_tokens = _extract_station_tokens_from_note(note)
        token_keys = {_normalize_station_lookup_key(tok) for tok in station_tokens}
        if station_norm and station_norm in token_keys and code:
            return row.get("name"), cell
    return None, None


def _apply_refine_operations(base_people_grid: dict, operations: list[dict]) -> tuple[dict, list[dict], list[str]]:
    preview_people_grid = json.loads(json.dumps(base_people_grid))
    diffs: list[dict] = []
    warnings: list[str] = []
    date_to_index, _, _ = _people_grid_to_lookup(preview_people_grid)

    for op in operations:
        op_type = op.get("type")
        if op_type == "set_shift":
            person = op.get("person")
            date_str = op.get("date")
            shift_code = op.get("shift")
            if not person or date_str not in date_to_index or not shift_code:
                warnings.append(f"REFINE_SKIPPED:set_shift:{person}:{date_str}:{shift_code}")
                continue
            resolved_name, row = _resolve_person_row(preview_people_grid, person)
            idx = date_to_index[date_str]
            cell = ((row.get("cells") or [])[idx]) or {}
            from_code = str(cell.get("code", "") or "")
            from_note = str(cell.get("note", "") or "")
            to_note = from_note
            row["cells"][idx] = {"code": shift_code, "note": to_note}
            diffs.append(
                {
                    "action": "set_shift",
                    "date": date_str,
                    "person": resolved_name,
                    "station": None,
                    "from": {"code": from_code, "note": from_note},
                    "to": {"code": shift_code, "note": to_note},
                }
            )
            continue

        if op_type == "set_off":
            person = op.get("person")
            date_str = op.get("date")
            if not person or date_str not in date_to_index:
                warnings.append(f"REFINE_SKIPPED:set_off:{person}:{date_str}")
                continue
            resolved_name, row = _resolve_person_row(preview_people_grid, person)
            idx = date_to_index[date_str]
            cell = ((row.get("cells") or [])[idx]) or {}
            from_code = str(cell.get("code", "") or "")
            from_note = str(cell.get("note", "") or "")
            to_note = "manual_refine:OFF"
            row["cells"][idx] = {"code": "OFF", "note": to_note}
            diffs.append(
                {
                    "action": "set_off",
                    "date": date_str,
                    "person": resolved_name,
                    "station": None,
                    "from": {"code": from_code, "note": from_note},
                    "to": {"code": "OFF", "note": to_note},
                }
            )
            continue

        if op_type == "replace_station":
            date_str = op.get("date")
            station = op.get("station")
            new_person = op.get("new_person")
            if not date_str or date_str not in date_to_index or not station or not new_person:
                warnings.append(f"REFINE_SKIPPED:replace_station:{date_str}:{station}:{new_person}")
                continue

            idx = date_to_index[date_str]
            old_person, old_cell = _find_station_holder(preview_people_grid, date_str, station)
            resolved_new_name, new_row = _resolve_person_row(preview_people_grid, new_person)
            new_cell = ((new_row.get("cells") or [])[idx]) or {}

            inherited_code = str((old_cell or {}).get("code", "") or "") or "A"
            to_note = f"manual_refine:{station}"
            from_new_code = str(new_cell.get("code", "") or "")
            from_new_note = str(new_cell.get("note", "") or "")
            new_row["cells"][idx] = {"code": inherited_code, "note": to_note}

            if old_person:
                resolved_old_name, old_row = _resolve_person_row(preview_people_grid, old_person)
                old_row["cells"][idx] = {"code": "", "note": f"manual_refine:removed_from:{station}"}
                diffs.append(
                    {
                        "action": "replace_station_old",
                        "date": date_str,
                        "person": resolved_old_name,
                        "station": station,
                        "from": {
                            "code": str((old_cell or {}).get("code", "") or ""),
                            "note": str((old_cell or {}).get("note", "") or ""),
                        },
                        "to": {"code": "", "note": f"manual_refine:removed_from:{station}"},
                    }
                )
            else:
                warnings.append(f"REFINE_NO_OLD_HOLDER:{date_str}:{station}")

            diffs.append(
                {
                    "action": "replace_station_new",
                    "date": date_str,
                    "person": resolved_new_name,
                    "station": station,
                    "from": {"code": from_new_code, "note": from_new_note},
                    "to": {"code": inherited_code, "note": to_note},
                }
            )
            continue

        if op_type == "add_station":
            date_str = op.get("date")
            station = op.get("station")
            person = op.get("person")
            if not date_str or date_str not in date_to_index or not station:
                warnings.append(f"REFINE_SKIPPED:add_station:{date_str}:{station}")
                continue

            idx = date_to_index[date_str]
            target_person = person
            if not target_person:
                for row in preview_people_grid.get("rows", []) or []:
                    cell = ((row.get("cells") or [])[idx]) or {}
                    if not str(cell.get("code", "") or ""):
                        target_person = row.get("name")
                        break
            if not target_person:
                warnings.append(f"REFINE_NO_FREE_PERSON:{date_str}:{station}")
                continue

            resolved_name, target_row = _resolve_person_row(preview_people_grid, target_person)
            target_cell = ((target_row.get("cells") or [])[idx]) or {}
            from_code = str(target_cell.get("code", "") or "")
            from_note = str(target_cell.get("note", "") or "")
            if from_code:
                warnings.append(f"REFINE_OVERWRITE:{resolved_name}:{date_str}")
            target_row["cells"][idx] = {"code": "A", "note": f"manual_refine:{station}"}
            diffs.append(
                {
                    "action": "add_station",
                    "date": date_str,
                    "person": resolved_name,
                    "station": station,
                    "from": {"code": from_code, "note": from_note},
                    "to": {"code": "A", "note": f"manual_refine:{station}"},
                }
            )
            continue

        warnings.append(f"REFINE_UNKNOWN_OP:{op_type}")

    return preview_people_grid, diffs, warnings


def _parse_refine_text(refine_text: str, *, start_date: str, people_grid: dict) -> tuple[list[dict], list[str], list[dict]]:
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

    station_lookup: dict[str, str] = {}
    for station in sorted(_known_refine_stations(people_grid)):
        station_lookup[_normalize_station_lookup_key(station)] = station
    shift_codes = _known_refine_shift_codes(people_grid)

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
            shift_or_off = _normalize_refine_shift(target_raw, shift_codes)
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


def _build_refine_lookup_context(*, start_date: str, people_grid: dict) -> dict:
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

    station_lookup: dict[str, str] = {}
    for station in sorted(_known_refine_stations(people_grid)):
        station_lookup[_normalize_station_lookup_key(station)] = station

    return {
        "anchor": anchor,
        "valid_dates": valid_dates,
        "person_lookup": person_lookup,
        "station_lookup": station_lookup,
        "shift_codes": _known_refine_shift_codes(people_grid),
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
        shift = _normalize_refine_shift(str(command.get("shift") or ""), shift_codes)
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
) -> tuple[list[dict], list[str], list[dict], dict]:
    warnings: list[str] = ["REFINE_LLM_FALLBACK_ATTEMPTED"]
    parse_errors: list[dict] = []
    explain: dict = {"parser": "llm_fallback_v1", "ops_count": 0, "fallback_used": True}

    llm_result = parse_refine_with_llm(
        refine_text=refine_text,
        year_month=year_month,
        language=language,
        known_people=_known_refine_people(people_grid),
        known_stations=sorted(_known_refine_stations(people_grid)),
        known_shift_codes=sorted(_known_refine_shift_codes(people_grid)),
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

    context = _build_refine_lookup_context(start_date=start_date, people_grid=people_grid)
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

def plan_to_people_grid(month_state, leave_requests):
    plan = month_state.get("plan", {}) or {}
    dates = sorted(plan.keys())

    # Current architecture truth: the monthly preview grid still derives its
    # people/role ordering from the JSON fixture, not from Django ORM models.
    workers = gd.load_json("workers.json").get("people", [])
    role_by_name = {
        p.get("name"): p.get("role", "")
        for p in workers
        if isinstance(p, dict) and p.get("name")
    }

    ordered_names = [p.get("name") for p in workers if isinstance(p, dict) and p.get("name")]

    for person in leave_requests.keys():
        if person not in role_by_name:
            role_by_name[person] = ""
        if person not in ordered_names:
            ordered_names.append(person)

    for date_str in dates:
        assignments = (plan.get(date_str) or {}).get("assignments", {}) or {}
        for _, recs in assignments.items():
            for rec in recs or []:
                name = rec.get("name")
                if not name:
                    continue
                if name not in role_by_name:
                    role_by_name[name] = ""
                if name not in ordered_names:
                    ordered_names.append(name)

    people = [{"name": name, "role": role_by_name.get(name, "")} for name in ordered_names]

    leave_by_person = {name: set(dates_list) for name, dates_list in leave_requests.items()}

    grid: dict[str, dict[str, dict]] = {name: {} for name in ordered_names}
    warnings: list[str] = list(month_state.get("warnings", []) or [])

    for date_str in dates:
        day_plan = plan.get(date_str, {}) or {}
        for warning in day_plan.get("warnings", []) or []:
            warnings.append(f"{date_str}:{warning}")

        assignments = day_plan.get("assignments", {}) or {}
        per_person: dict[str, dict] = {}
        per_person_count: dict[str, int] = {}

        for station, recs in assignments.items():
            for rec in recs or []:
                name = rec.get("name")
                if not name:
                    continue

                per_person_count[name] = per_person_count.get(name, 0) + 1

                notes = rec.get("notes", [])
                if isinstance(notes, list):
                    note_list = notes
                elif notes:
                    note_list = [str(notes)]
                else:
                    note_list = []

                if name not in per_person:
                    per_person[name] = {
                        "code": rec.get("shift", ""),
                        "station": station,
                        "notes": note_list,
                    }

        for name, count in per_person_count.items():
            if count > 1:
                warnings.append(f"MULTI_ASSIGN:{name}:{date_str}")

        for name in ordered_names:
            if name in per_person:
                grid[name][date_str] = per_person[name]
            elif date_str in leave_by_person.get(name, set()):
                grid[name][date_str] = {"code": "OFF", "station": "", "notes": []}
            else:
                grid[name][date_str] = {"code": "", "station": "", "notes": []}

    people_grid, legend = _build_people_grid_and_legend(month_state, ordered_names, role_by_name, grid)
    weekly_rest_warnings = _build_weekly_rest_warnings_from_people_grid(people_grid)

    return {
        "meta": {
            "month_start": month_state.get("month_start"),
            "month_end": month_state.get("month_end"),
            "language": month_state.get("language", "ja"),
        },
        "dates": dates,
        "people": people,
        "grid": grid,
        "warnings": warnings,
        "weekly_rest_warnings": weekly_rest_warnings,
        "summary": month_state.get("summary", {}),
        "overtime": month_state.get("overtime", {}),
        "people_grid": people_grid,
        "legend": legend,
    }


@csrf_exempt
@require_http_methods(["POST"])
def api_monthly_preview_mirror(request):
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    start_date, date_err = _validate_year_month(payload.get("year_month"))
    if date_err:
        return JsonResponse({"detail": date_err}, json_dumps_params={"ensure_ascii": False}, status=400)

    leave_requests, leave_by_date, leave_err = _validate_leave_requests(payload.get("leave_requests"))
    if leave_err:
        return JsonResponse({"detail": leave_err}, json_dumps_params={"ensure_ascii": False}, status=400)

    language = payload.get("language") or "ja"

    month_state = _generate_month_state_with_leave_requests(start_date, leave_by_date)
    month_state["language"] = language

    try:
        result = plan_to_people_grid(month_state, leave_requests)
    except (ShiftDefsNotFound, ShiftDefsInvalid) as exc:
        return JsonResponse({"detail": str(exc)}, json_dumps_params={"ensure_ascii": False}, status=500)

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def api_monthly_export_csv(request):
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    start_date, date_err = _validate_year_month(payload.get("year_month"))
    if date_err:
        return JsonResponse({"detail": date_err}, json_dumps_params={"ensure_ascii": False}, status=400)
    validated_year_month = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y-%m")

    leave_requests, leave_by_date, leave_err = _validate_leave_requests(payload.get("leave_requests"))
    if leave_err:
        return JsonResponse({"detail": leave_err}, json_dumps_params={"ensure_ascii": False}, status=400)

    month_state = _generate_month_state_with_leave_requests(start_date, leave_by_date)
    month_state["language"] = payload.get("language") or "ja"

    try:
        preview = plan_to_people_grid(month_state, leave_requests)
    except (ShiftDefsNotFound, ShiftDefsInvalid) as exc:
        return JsonResponse({"detail": str(exc)}, json_dumps_params={"ensure_ascii": False}, status=500)

    people_grid = preview.get("people_grid", {})
    dates = people_grid.get("dates", [])
    rows = people_grid.get("rows", [])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "role", *dates])
    for row in rows:
        cells = row.get("cells", [])
        writer.writerow(
            [row.get("name", ""), row.get("role", "")]
            + [((cell or {}).get("code", "")) for cell in cells]
        )

    response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="monthly_{validated_year_month}.csv"'
    return response


@csrf_exempt
@require_http_methods(["POST"])
def api_monthly_transcribe(request):
    audio_file = request.FILES.get("audio")
    if audio_file is None:
        return JsonResponse(
            {"ok": False, "detail": "Missing audio file."},
            json_dumps_params={"ensure_ascii": False},
            status=400,
        )

    language = str(request.POST.get("language") or "").strip().lower() or None

    try:
        text = transcribe_uploaded_audio(audio_file, language=language)
    except AudioTranscriptionError as exc:
        return JsonResponse(
            {"ok": False, "detail": str(exc)},
            json_dumps_params={"ensure_ascii": False},
            status=502,
        )

    return JsonResponse(
        {"ok": True, "text": text},
        json_dumps_params={"ensure_ascii": False},
        status=200,
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_monthly_refine_mirror(request):
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    start_date, date_err = _validate_year_month(payload.get("year_month"))
    if date_err:
        return JsonResponse({"detail": date_err}, json_dumps_params={"ensure_ascii": False}, status=400)

    leave_requests, leave_by_date, leave_err = _validate_leave_requests(payload.get("leave_requests"))
    if leave_err:
        return JsonResponse({"detail": leave_err}, json_dumps_params={"ensure_ascii": False}, status=400)

    language = _normalize_refine_language(payload.get("language") or "ja")
    year_month = str(payload.get("year_month") or "")
    refine_text = str(payload.get("refine_text") or "")

    # Current monthly demo path: build a request-scoped preview from JSON-backed
    # engine inputs plus request leave overrides. No monthly plan is persisted here.
    month_state = _generate_month_state_with_leave_requests(start_date, leave_by_date)
    month_state["language"] = language

    try:
        preview = plan_to_people_grid(month_state, leave_requests)
    except (ShiftDefsNotFound, ShiftDefsInvalid) as exc:
        return JsonResponse({"detail": str(exc)}, json_dumps_params={"ensure_ascii": False}, status=500)

    ops, parse_warnings, parse_errors = _parse_refine_text(
        refine_text,
        start_date=start_date,
        people_grid=preview.get("people_grid", {}),
    )
    parser_name = "rule_based_v2"
    fallback_used = False

    if parse_errors and not ops:
        llm_ops, llm_warnings, llm_parse_errors, llm_explain = _parse_refine_text_with_llm_fallback(
            refine_text=refine_text,
            year_month=year_month,
            start_date=start_date,
            language=language,
            people_grid=preview.get("people_grid", {}),
        )
        parse_warnings.extend(llm_warnings)

        if llm_ops and not llm_parse_errors:
            ops = llm_ops
            parse_errors = []
            parser_name = str(llm_explain.get("parser") or "llm_fallback_v1")
            fallback_used = True
        else:
            all_parse_errors = list(parse_errors) + list(llm_parse_errors)
            localized_errors = _localize_parse_errors(all_parse_errors, language)
            detail = _build_refine_detail(localized_errors, language=language)
            if not localized_errors:
                localized_errors = [
                    _refine_parse_error(
                        refine_text,
                        "llm_unknown",
                        _refine_error_message(language, "llm_unknown"),
                    )
                ]
                detail = _build_refine_detail(localized_errors, language=language)
            return JsonResponse(
                {
                    "ok": False,
                    "detail": detail,
                    "parse_errors": localized_errors,
                },
                json_dumps_params={"ensure_ascii": False},
                status=400,
            )

    localized_parse_errors = _localize_parse_errors(parse_errors, language)

    if parse_errors and not ops:
        detail = _build_refine_detail(localized_parse_errors, language=language)
        return JsonResponse(
            {
                "ok": False,
                "detail": detail,
                "parse_errors": localized_parse_errors,
            },
            json_dumps_params={"ensure_ascii": False},
            status=400,
        )

    preview_people_grid, diff, refine_warnings = _apply_refine_operations(preview.get("people_grid", {}), ops)

    warnings = list(preview.get("warnings", []) or [])
    warnings.extend(parse_warnings)
    warnings.extend(refine_warnings)
    weekly_rest_warnings = _build_weekly_rest_warnings_from_people_grid(preview_people_grid)

    return JsonResponse(
        {
            "ok": True,
            "diff": diff,
            "preview_people_grid": preview_people_grid,
            "warnings": warnings,
            "parse_errors": localized_parse_errors,
            "weekly_rest_warnings": weekly_rest_warnings,
            "explain": {"parser": parser_name, "ops_count": len(ops), "fallback_used": fallback_used},
        },
        json_dumps_params={"ensure_ascii": False},
        status=200,
    )

@require_http_methods(["GET"])
def api_month_mirror(request):
    start_date = request.GET.get("start_date")
    return JsonResponse(_generate_month_state(start_date), json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_month_csv_mirror(request):
    start_date = request.GET.get("start_date")
    state = _generate_month_state(start_date)
    month_start = state["month_start"]
    plan = state["plan"]

    rows: list[dict] = []
    for date_str, day_plan in plan.items():
        chefs = ",".join(day_plan.get("chefs_present", []))
        hours = day_plan.get("hours_estimate", {})
        for station, assignments in day_plan.get("assignments", {}).items():
            for rec in assignments:
                name = rec["name"]
                shift = rec["shift"]
                rows.append(
                    {
                        "date": date_str,
                        "station": station,
                        "name": name,
                        "shift": shift,
                        "shift_hours": hours.get(name, 0.0),
                        "chef_present": chefs,
                    }
                )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["date", "station", "name", "shift", "shift_hours", "chef_present"])
    writer.writeheader()
    writer.writerows(rows)

    response = HttpResponse(buf.getvalue().encode("utf-8-sig"), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="month_{month_start}.csv"'
    return response


@require_http_methods(["GET"])
def api_calendar_month_mirror(request):
    start_date = request.GET.get("start_date", "")
    return JsonResponse(build_month(start_date), json_dumps_params={"ensure_ascii": False}, status=200)


@require_http_methods(["GET"])
def api_calendar_month_csv_mirror(request):
    start_date = request.GET.get("start_date", "")
    data = build_month(start_date)
    if not data.get("success"):
        return HttpResponse(",".join(data.get("errors", ["UNKNOWN_ERROR"])), content_type="text/plain", status=400)

    rows = data.get("rows")
    if rows is None:
        rows = []
        for d in data.get("days", []):
            for station, entries in (d.get("assignments", {}) or {}).items():
                for e in entries or []:
                    rows.append(
                        {
                            "date": d.get("date"),
                            "station": station,
                            "name": e.get("name", ""),
                            "shift": e.get("shift", ""),
                        }
                    )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["date", "station", "name", "shift"])
    writer.writeheader()
    writer.writerows(rows)

    response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="month_{start_date}.csv"'
    return response

