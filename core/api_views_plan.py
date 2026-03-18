"""Migration-era plan mirror API views."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from app.plan_service import (
    create_plan,
    delete_plan,
    get_plan,
    list_all_plans,
    patch_apply,
    patch_preview,
)
from core.api_view_helpers import _parse_request_payload


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
