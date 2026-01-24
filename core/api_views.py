# core/api_views.py
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import ScheduleRun
from app.month_service import run_daily_schedule
from app.run_service import build_out_from_run
from app.presenter import present_run_out


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
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON body"}, status=400)

    date_str = payload.get("date")
    if not date_str:
        return JsonResponse({"ok": False, "error": "Missing 'date' in body"}, status=400)

    absent = payload.get("absent") or []
    if not isinstance(absent, list):
        return JsonResponse({"ok": False, "error": "'absent' must be a list"}, status=400)

    # 1) 產生 + 存 DB
    run = run_daily_schedule(tenant_name, date_str, absent=absent)

    # 2) 從 DB 組回 out
    out = build_out_from_run(run)
    presented = present_run_out(date=date_str, out=out)

    return JsonResponse(
        {"ok": True, "run_id": run.id, "out": presented},
        json_dumps_params={"ensure_ascii": False},
        status=201,
    )


@require_http_methods(["GET"])
def get_run_out(request, run_id: int):
    try:
        run = ScheduleRun.objects.get(id=run_id)
    except ScheduleRun.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Run not found"}, status=404)

    out = build_out_from_run(run)

    # 如果你的欄位不是 run.date，改成實際欄位，例如 run.run_date / run.target_date
    date_str = str(run.date)

    presented = present_run_out(date=date_str, out=out)

    return JsonResponse(
        {"ok": True, "run_id": run.id, "out": presented},
        json_dumps_params={"ensure_ascii": False},
        status=200,
    )
