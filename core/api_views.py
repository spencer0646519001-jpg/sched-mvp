# core/api_views.py
import json
import csv
import io
from datetime import date, timedelta, datetime

from django.http import JsonResponse
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from dateutil import parser as dtparser
from core.presenters.daily_run_presenter import (present_create_daily_run_success,present_create_daily_run_graph_success,)

from core.models import ScheduleRun
from app.month_service import run_daily_schedule
from app.run_service import build_out_from_run
from app.presenter import (
    present_run_out,
    present_api_success,
    present_api_error,
)
from app import generate_day as gd
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

    和 create_daily_run 一樣，但：
    - 用 LangGraph 包 greedy
    - 回傳 explanations
    """
    # 1) parse JSON
    payload, payload_err = _parse_request_payload(request)
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 2) validate
    date_str, absent, payload_err = _validate_daily_run_payload(
        payload,
        include_absent_type=False,
    )
    if payload_err:
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 3) run LangGraph (greedy inside)
    from app.langgraph_flow import run_daily_schedule_graph

    result = run_daily_schedule_graph(
    tenant_name=tenant_name,
    date_str=date_str,
    absent=absent,
)

    # ✅ 新版：run_daily_schedule_graph 回傳 {"ok": True, "data": {...}, "compat": {...}}
    data = result.get("data") or {}
    compat = result.get("compat") or {}

    out = data.get("out") or compat.get("out_engine")
    decision_trace = data.get("decision_trace") or compat.get("decision_trace") or []
    explanations = data.get("explanations") or compat.get("explanations") or {}
    metrics = data.get("metrics") or {}

    if out is None:
        raise KeyError("run_daily_schedule_graph returned no out/data.out (and no compat.out_engine)")

    out["explanations"] = explanations


    presented = present_run_out(date=date_str, out=out)

    payload_ok = present_create_daily_run_graph_success(out=presented)

    return JsonResponse(payload_ok, json_dumps_params={"ensure_ascii": False}, status=201)


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


def _generate_month_state(start_date_str: str) -> dict:
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

        week_state = generate_week(cur.isoformat(), num_days=chunk_days, prev_state=prev_state)
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
    original_greedy_assign = gd.greedy_assign

    def _greedy_assign_with_leave(date_str: str, absent):
        base_absent = absent or []
        leave_absent = leave_by_date.get(date_str, [])
        absent_today = list(dict.fromkeys(base_absent + leave_absent))
        return original_greedy_assign(date_str, absent_today)

    gd.greedy_assign = _greedy_assign_with_leave
    try:
        return _generate_month_state(start_date_str)
    finally:
        gd.greedy_assign = original_greedy_assign


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


def plan_to_people_grid(month_state, leave_requests):
    plan = month_state.get("plan", {}) or {}
    dates = sorted(plan.keys())

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

    month_state = _generate_month_state(start_date)
    month_state["language"] = payload.get("language") or "ja"

    try:
        preview = plan_to_people_grid(month_state, {})
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
