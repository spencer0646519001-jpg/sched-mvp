# core/api_views.py
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import ScheduleRun
from app.month_service import run_daily_schedule
from app.run_service import build_out_from_run
from app.presenter import (
    present_run_out,
    present_api_success,
    present_api_error,
)
from app.langgraph_flow import run_daily_schedule_graph


@csrf_exempt
@require_http_methods(["POST"])
def create_daily_run(request, tenant_name: str):
    """
    POST body:
    {
      "date": "2026-01-06",
      "absent": ["Kim", "Spencer"]
    }
    """
    # 1) parse JSON
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload_err = present_api_error(
            code="invalid_json",
            message="Invalid JSON body",
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 2) validate
    date_str = payload.get("date")
    if not date_str:
        payload_err = present_api_error(
            code="missing_date",
            message="Missing 'date' in body",
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    absent = payload.get("absent") or []
    if not isinstance(absent, list):
        payload_err = present_api_error(
            code="invalid_absent",
            message="'absent' must be a list",
            details={"absent_type": type(absent).__name__},
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 3) run engine + save DB
    run = run_daily_schedule(tenant_name, date_str, absent=absent)

    # 4) build + present out
    out = build_out_from_run(run)
    presented = present_run_out(date=date_str, out=out)

    payload_ok = present_api_success(
        data={"run_id": run.id, "out": presented},
        meta={"engine_version": "0.1"},
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
    presented = present_run_out(date=str(run.date), out=out)

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
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload_err = present_api_error(
            code="invalid_json",
            message="Invalid JSON body",
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 2) validate
    date_str = payload.get("date")
    if not date_str:
        payload_err = present_api_error(
            code="missing_date",
            message="Missing 'date' in body",
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    absent = payload.get("absent") or []
    if not isinstance(absent, list):
        payload_err = present_api_error(
            code="invalid_absent",
            message="'absent' must be a list",
        )
        return JsonResponse(payload_err, json_dumps_params={"ensure_ascii": False}, status=400)

    # 3) run LangGraph (greedy inside)
    result = run_daily_schedule_graph(
        tenant_name=tenant_name,
        date_str=date_str,
        absent=absent,
    )

    # 4) presenter（沿用你已經很乾淨的 presenter）
    out = result["out_engine"]
    out["explanations"] = result.get("explanations", {})

    presented = present_run_out(date=date_str, out=out)

    payload_ok = present_api_success(
        data={"out": presented},
        meta={"engine_version": "0.1"},
    )
    return JsonResponse(payload_ok, json_dumps_params={"ensure_ascii": False}, status=201)
