"""Monthly, weekly, calendar, and monthly-demo API views."""

import csv
import io
import re
from datetime import date, datetime, timedelta

from dateutil import parser as dtparser
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from app import generate_day as gd
from app.domain.normalize import canonical_shift
from app.infra.shift_metadata import serialize_shift_metadata
from app.infra.station_metadata import serialize_station_metadata
from app.generate_week import generate_week, summarize_week
from app.infra.monthly_scheduling_inputs import build_monthly_scheduling_inputs
from app.month_service import build_month
from core import monthly_refine_apply, monthly_refine_parser, monthly_workspace_service
from core.api_view_helpers import _parse_request_payload
from core.refine_llm import parse_refine_with_llm
from core.shift_defs import (
    ShiftDefsInvalid,
    ShiftDefsNotFound,
    build_shift_legend,
    load_shift_defs,
)
from core.transcribe_audio import AudioTranscriptionError, transcribe_uploaded_audio


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
    engine_inputs=None,
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
            inputs=engine_inputs,
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


def _generate_month_state_with_leave_requests(
    start_date_str: str,
    leave_by_date: dict[str, list[str]],
    engine_inputs=None,
) -> dict:
    kwargs = {"leave_by_date": leave_by_date}
    if engine_inputs is not None:
        kwargs["engine_inputs"] = engine_inputs
    return _generate_month_state(start_date_str, **kwargs)


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


def _normalize_shift_lookup_key(raw: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(raw or "")).strip().lower()


def _monthly_shift_metadata_payload(shift_metadata) -> list[dict[str, object]]:
    serialized = serialize_shift_metadata(shift_metadata)
    if not serialized:
        serialized = [dict(item) for item in load_shift_defs() if isinstance(item, dict)]

    legend = build_shift_legend(serialized)
    payload: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in serialized:
        code = canonical_shift(item.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        copied = dict(item)
        copied["code"] = code
        copied["display_name"] = str(copied.get("display_name") or code).strip() or code
        copied["legend_label"] = str(copied.get("legend_label") or "").strip()
        copied["label"] = str((legend.get(code) or {}).get("label") or "")
        payload.append(copied)
    return payload


def _build_people_grid_and_legend(
    month_state: dict,
    ordered_names: list[str],
    role_by_name: dict[str, str],
    grid: dict[str, dict[str, dict]],
    *,
    shift_metadata=None,
) -> tuple[dict, dict, list[dict[str, object]]]:
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

    shift_metadata_payload = _monthly_shift_metadata_payload(shift_metadata)
    legend = build_shift_legend(shift_metadata_payload)
    for code in sorted(used_codes):
        if code not in legend:
            legend[code] = {"label": "Shift code"}

    return {
        "year_month": year_month,
        "dates": dates,
        "rows": rows,
    }, legend, shift_metadata_payload



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


# Refine implementation now lives in dedicated modules. Keep these wrapper
# names in the view module so existing hook wiring and monkeypatch-based
# tests still bind at the same seam points.


def _refine_parse_error(line: str, code: str, message: str) -> dict:
    return monthly_refine_parser._refine_parse_error(line, code, message)


def _normalize_refine_language(language: str) -> str:
    return monthly_refine_parser._normalize_refine_language(language)


def _refine_error_message(language: str, code: str) -> str:
    return monthly_refine_parser._refine_error_message(language, code)


def _localize_parse_errors(parse_errors: list[dict], language: str) -> list[dict]:
    return monthly_refine_parser._localize_parse_errors(parse_errors, language)


def _build_refine_detail(parse_errors: list[dict], *, language: str) -> str:
    return monthly_refine_parser._build_refine_detail(parse_errors, language=language)


def _annotate_refine_diff_station_metadata(diff: list[dict], *, station_metadata) -> list[dict]:
    return monthly_refine_apply._annotate_refine_diff_station_metadata(
        diff,
        station_metadata=station_metadata,
    )


def _apply_refine_operations(base_people_grid: dict, operations: list[dict]) -> tuple[dict, list[dict], list[str]]:
    return monthly_refine_apply._apply_refine_operations(base_people_grid, operations)


def _parse_refine_text(
    refine_text: str,
    *,
    start_date: str,
    people_grid: dict,
    station_metadata=None,
    shift_metadata=None,
) -> tuple[list[dict], list[str], list[dict]]:
    return monthly_refine_parser._parse_refine_text(
        refine_text,
        start_date=start_date,
        people_grid=people_grid,
        station_metadata=station_metadata,
        shift_metadata=shift_metadata,
    )


def _parse_refine_text_with_llm_fallback(
    *,
    refine_text: str,
    year_month: str,
    start_date: str,
    language: str,
    people_grid: dict,
    station_metadata=None,
    shift_metadata=None,
) -> tuple[list[dict], list[str], list[dict], dict]:
    return monthly_refine_parser._parse_refine_text_with_llm_fallback(
        refine_text=refine_text,
        year_month=year_month,
        start_date=start_date,
        language=language,
        people_grid=people_grid,
        station_metadata=station_metadata,
        shift_metadata=shift_metadata,
        parse_refine_with_llm_hook=parse_refine_with_llm,
    )


def _monthly_preview_hooks() -> monthly_workspace_service.MonthlyPreviewHooks:
    return monthly_workspace_service.MonthlyPreviewHooks(
        generate_month_state_with_leave_requests=_generate_month_state_with_leave_requests,
        plan_to_people_grid=plan_to_people_grid,
    )


def _build_monthly_preview(scheduling_inputs) -> dict:
    """Build the canonical monthly preview from one centralized input contract."""
    return monthly_workspace_service.build_monthly_preview(
        scheduling_inputs,
        hooks=_monthly_preview_hooks(),
    )


def _is_valid_monthly_people_grid(people_grid) -> bool:
    if not isinstance(people_grid, dict):
        return False

    dates = people_grid.get("dates")
    rows = people_grid.get("rows")
    if not isinstance(dates, list) or not isinstance(rows, list):
        return False
    if any(not isinstance(date_str, str) for date_str in dates):
        return False

    for row in rows:
        if not isinstance(row, dict):
            return False
        if not isinstance(row.get("name", ""), str):
            return False

        role = row.get("role", "")
        if role is not None and not isinstance(role, str):
            return False

        cells = row.get("cells")
        if not isinstance(cells, list) or len(cells) != len(dates):
            return False

        for cell in cells:
            if not isinstance(cell, dict):
                return False
            code = cell.get("code", "")
            note = cell.get("note", "")
            if code is not None and not isinstance(code, str):
                return False
            if note is not None and not isinstance(note, str):
                return False

    return True


def _monthly_workspace_hooks() -> monthly_workspace_service.MonthlyWorkspaceHooks:
    return monthly_workspace_service.MonthlyWorkspaceHooks(
        build_monthly_preview=_build_monthly_preview,
        is_valid_monthly_people_grid=_is_valid_monthly_people_grid,
        parse_refine_text=_parse_refine_text,
        parse_refine_text_with_llm_fallback=_parse_refine_text_with_llm_fallback,
        localize_parse_errors=_localize_parse_errors,
        build_refine_detail=_build_refine_detail,
        refine_parse_error=_refine_parse_error,
        refine_error_message=_refine_error_message,
        apply_refine_operations=_apply_refine_operations,
        annotate_refine_diff_station_metadata=_annotate_refine_diff_station_metadata,
        build_weekly_rest_warnings_from_people_grid=_build_weekly_rest_warnings_from_people_grid,
    )


def _resolve_monthly_export_people_grid(payload: dict, scheduling_inputs) -> dict:
    return monthly_workspace_service.resolve_monthly_export_people_grid(
        payload,
        scheduling_inputs,
        hooks=_monthly_workspace_hooks(),
    )


def plan_to_people_grid(month_state, scheduling_inputs):
    plan = month_state.get("plan", {}) or {}
    dates = sorted(plan.keys())

    role_by_name = dict(scheduling_inputs.role_by_name)
    ordered_names = list(scheduling_inputs.ordered_names)
    leave_requests = scheduling_inputs.leave_requests

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

    people_grid, legend, shift_metadata = _build_people_grid_and_legend(
        month_state,
        ordered_names,
        role_by_name,
        grid,
        shift_metadata=getattr(scheduling_inputs, "shift_metadata", None),
    )
    weekly_rest_warnings = _build_weekly_rest_warnings_from_people_grid(people_grid)
    station_metadata = serialize_station_metadata(getattr(scheduling_inputs, "station_metadata", None))

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
        "shift_metadata": shift_metadata,
        "station_metadata": station_metadata,
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
    scheduling_inputs = build_monthly_scheduling_inputs(
        start_date=start_date,
        language=language,
        leave_requests=leave_requests,
        leave_by_date=leave_by_date,
    )

    try:
        result = monthly_workspace_service.build_monthly_preview_payload(
            scheduling_inputs,
            hooks=_monthly_workspace_hooks(),
        )
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
    scheduling_inputs = build_monthly_scheduling_inputs(
        start_date=start_date,
        language=payload.get("language") or "ja",
        leave_requests=leave_requests,
        leave_by_date=leave_by_date,
    )

    try:
        csv_body = monthly_workspace_service.build_monthly_export_csv(
            payload,
            scheduling_inputs,
            hooks=_monthly_workspace_hooks(),
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, json_dumps_params={"ensure_ascii": False}, status=400)
    except (ShiftDefsNotFound, ShiftDefsInvalid) as exc:
        return JsonResponse({"detail": str(exc)}, json_dumps_params={"ensure_ascii": False}, status=500)

    response = HttpResponse(csv_body, content_type="text/csv; charset=utf-8")
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
    scheduling_inputs = build_monthly_scheduling_inputs(
        start_date=start_date,
        language=language,
        leave_requests=leave_requests,
        leave_by_date=leave_by_date,
    )

    try:
        result = monthly_workspace_service.refine_monthly_workspace(
            scheduling_inputs=scheduling_inputs,
            year_month=year_month,
            start_date=start_date,
            language=language,
            refine_text=refine_text,
            hooks=_monthly_workspace_hooks(),
        )
    except (ShiftDefsNotFound, ShiftDefsInvalid) as exc:
        return JsonResponse({"detail": str(exc)}, json_dumps_params={"ensure_ascii": False}, status=500)

    return JsonResponse(
        result.payload,
        json_dumps_params={"ensure_ascii": False},
        status=result.status_code,
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
