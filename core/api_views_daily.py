"""Health, daily-run, and graph-backed daily API views."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from app import generate_day as gd
from app.domain.normalize import canonical_station
from app.infra.station_metadata import load_station_metadata_overlay, serialize_station_metadata
from app.month_service import run_daily_schedule
from app.presenter import present_api_error, present_api_success, present_run_out
from app.run_service import build_out_from_run
from core.api_view_helpers import _parse_request_payload, _validate_daily_run_payload
from core.models import ScheduleRun
from core.presenters.daily_run_presenter import present_create_daily_run_success


def _ordered_station_codes_from_graph_output(out, trace, explanations) -> list[str]:
    ordered_codes: list[str] = []
    seen: set[str] = set()

    def remember(raw_station) -> None:
        code = canonical_station(str(raw_station or ""))
        if not code or code in seen:
            return
        ordered_codes.append(code)
        seen.add(code)

    if isinstance(trace, list):
        for item in trace:
            if isinstance(item, dict):
                remember(item.get("station"))

    if isinstance(explanations, dict):
        for station in explanations.keys():
            remember(station)

    assignments = out.get("assignments") if isinstance(out, dict) else {}
    if isinstance(assignments, dict):
        for station in assignments.keys():
            remember(station)

    return ordered_codes


def _annotate_trace_station_labels(trace, station_labels: dict[str, str]) -> list[dict]:
    if not isinstance(trace, list):
        return []

    annotated: list[dict] = []
    for item in trace:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        station = canonical_station(str(copied.get("station") or ""))
        if station:
            copied["station_label"] = station_labels.get(station, station)
        annotated.append(copied)
    return annotated


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
    station_codes = _ordered_station_codes_from_graph_output(out, trace, explanations)
    station_metadata_overlay = load_station_metadata_overlay(
        tenant_name=tenant_name,
        base_station_codes=station_codes,
    )
    station_labels = dict(getattr(station_metadata_overlay, "labels", {}) or {})
    trace_with_labels = _annotate_trace_station_labels(trace, station_labels)
    serialized_station_metadata = serialize_station_metadata(
        station_metadata_overlay,
        station_codes=station_codes,
    )

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
            "trace": trace_with_labels,
            "text": text,
            "metrics": metrics if isinstance(metrics, dict) else {},
            "explanations": explanations if isinstance(explanations, dict) else {},
            "station_labels": station_labels,
            "station_metadata": serialized_station_metadata,
            # backward compatibility for existing clients
            "data": {
                "out": presented,
                "decision_trace": trace_with_labels,
                "explanations": explanations if isinstance(explanations, dict) else {},
                "metrics": metrics if isinstance(metrics, dict) else {},
            },
            "meta": {"engine_version": "0.1"},
        },
        json_dumps_params={"ensure_ascii": False},
        status=200,
    )
