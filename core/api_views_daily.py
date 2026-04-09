"""Health, daily-run, and graph-backed daily API views."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from app import generate_day as gd
from app.domain.normalize import canonical_shift, canonical_station
from app.infra.engine_input_resolver import (
    UnsupportedEngineInputTenant,
    require_supported_engine_input_tenant,
    resolve_engine_inputs_for_tenant,
    supported_engine_input_tenants,
)
from app.infra.schedule_run_repo import DailyRunPersistenceFixtureError
from app.infra.shift_metadata import load_shift_metadata_overlay, serialize_shift_metadata
from app.infra.station_metadata import load_station_metadata_overlay, serialize_station_metadata
from app.month_service import run_daily_schedule
from app.presenter import present_api_error, present_api_success, present_run_out
from app.run_service import build_out_from_run
from core.api_view_helpers import _parse_request_payload, _validate_daily_run_payload
from core.models import ScheduleRun
from core.presenters.daily_run_presenter import present_create_daily_run_success
from core.shift_defs import build_shift_legend


def _unsupported_tenant_response(exc: UnsupportedEngineInputTenant) -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "code": "unsupported_tenant",
            "detail": str(exc),
            "tenant_name": exc.tenant_name,
            "supported_tenants": supported_engine_input_tenants(),
        },
        json_dumps_params={"ensure_ascii": False},
        status=400,
    )


def _persistence_fixture_error_response(exc: DailyRunPersistenceFixtureError) -> JsonResponse:
    payload_err = present_api_error(
        code="persistence_fixtures_incomplete",
        message="Daily-run persistence fixtures are incomplete for this tenant.",
        details={
            "tenant_name": exc.tenant_name,
            "missing_station_codes": list(exc.missing_station_codes),
            "missing_employee_names": list(exc.missing_employee_names),
        },
    )
    return JsonResponse(
        payload_err,
        json_dumps_params={"ensure_ascii": False},
        status=409,
    )


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


def _load_daily_shift_metadata_overlay(tenant_name: str):
    try:
        base_shift_defs = getattr(
            resolve_engine_inputs_for_tenant(tenant_name),
            "shifts_list",
            [],
        ) or []
    except UnsupportedEngineInputTenant:
        raise
    except Exception:
        base_shift_defs = []
    return load_shift_metadata_overlay(
        tenant_name=tenant_name,
        base_shift_defs=base_shift_defs,
    )


def _ordered_shift_codes_from_presented_out(presented_out: dict) -> list[str]:
    ordered_codes: list[str] = []
    seen: set[str] = set()

    data = presented_out.get("data") if isinstance(presented_out, dict) else {}
    assignments = data.get("assignments") if isinstance(data, dict) else []
    if not isinstance(assignments, list):
        return []

    for item in assignments:
        if not isinstance(item, dict):
            continue
        assignees = item.get("assignees") or []
        if not isinstance(assignees, list):
            continue
        for assignee in assignees:
            if not isinstance(assignee, dict):
                continue
            code = canonical_shift(str(assignee.get("shift") or ""))
            if not code or code in seen:
                continue
            ordered_codes.append(code)
            seen.add(code)

    return ordered_codes


def _daily_shift_metadata_payload(shift_metadata_overlay, *, shift_codes: list[str]) -> list[dict[str, object]]:
    serialized = serialize_shift_metadata(shift_metadata_overlay, shift_codes=shift_codes)
    if not serialized:
        return []

    legend = build_shift_legend(serialized)
    payload: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in serialized:
        code = canonical_shift(str(item.get("code") or ""))
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


def _annotate_trace_shift_metadata(
    trace: list[dict],
    *,
    presented_out: dict,
    shift_metadata_payload: list[dict[str, object]],
) -> list[dict]:
    if not isinstance(trace, list):
        return []

    shift_metadata_by_code: dict[str, dict[str, object]] = {}
    for item in shift_metadata_payload:
        if not isinstance(item, dict):
            continue
        code = canonical_shift(str(item.get("code") or ""))
        if code:
            shift_metadata_by_code[code] = dict(item)

    assignments_by_station: dict[str, list[dict]] = {}
    data = presented_out.get("data") if isinstance(presented_out, dict) else {}
    assignments = data.get("assignments") if isinstance(data, dict) else []
    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, dict):
                continue
            station = canonical_station(str(item.get("station") or ""))
            assignees = item.get("assignees") or []
            if station and isinstance(assignees, list):
                assignments_by_station[station] = [assignee for assignee in assignees if isinstance(assignee, dict)]

    annotated: list[dict] = []
    for item in trace:
        if not isinstance(item, dict):
            continue

        copied = dict(item)
        station = canonical_station(str(copied.get("station") or ""))
        assignees = assignments_by_station.get(station, [])

        picked_details: list[dict[str, object]] = []
        for assignee in assignees:
            name = str(assignee.get("name") or "").strip()
            shift = canonical_shift(str(assignee.get("shift") or ""))
            metadata = shift_metadata_by_code.get(shift, {})

            detail: dict[str, object] = {}
            if name:
                detail["name"] = name
            if shift:
                detail["shift"] = shift
            if metadata.get("display_name"):
                detail["shift_display_name"] = metadata["display_name"]
            if metadata.get("legend_label"):
                detail["shift_legend_label"] = metadata["legend_label"]
            if metadata.get("label"):
                detail["shift_label"] = metadata["label"]
            if metadata.get("paid_hours") is not None:
                detail["shift_paid_hours"] = metadata["paid_hours"]

            if detail:
                picked_details.append(detail)

        if picked_details:
            copied["picked_details"] = picked_details
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
    try:
        run = run_daily_schedule(tenant_name, date_str, absent=absent)
    except UnsupportedEngineInputTenant as exc:
        return _unsupported_tenant_response(exc)
    except DailyRunPersistenceFixtureError as exc:
        return _persistence_fixture_error_response(exc)

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
    language = "en"

    try:
        require_supported_engine_input_tenant(tenant_name)
    except UnsupportedEngineInputTenant as exc:
        return _unsupported_tenant_response(exc)

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
    except UnsupportedEngineInputTenant as exc:
        return _unsupported_tenant_response(exc)
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
    shift_metadata_overlay = _load_daily_shift_metadata_overlay(tenant_name)
    shift_codes = _ordered_shift_codes_from_presented_out(presented)
    serialized_shift_metadata = _daily_shift_metadata_payload(
        shift_metadata_overlay,
        shift_codes=shift_codes,
    )
    station_labels = dict(getattr(station_metadata_overlay, "labels", {}) or {})
    trace_with_labels = _annotate_trace_station_labels(trace, station_labels)
    trace_with_labels = _annotate_trace_shift_metadata(
        trace_with_labels,
        presented_out=presented,
        shift_metadata_payload=serialized_shift_metadata,
    )
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
            "shift_metadata": serialized_shift_metadata,
            # backward compatibility for existing clients
            "data": {
                "out": presented,
                "decision_trace": trace_with_labels,
                "explanations": explanations if isinstance(explanations, dict) else {},
                "metrics": metrics if isinstance(metrics, dict) else {},
                "shift_metadata": serialized_shift_metadata,
            },
            "meta": {"engine_version": "0.1"},
        },
        json_dumps_params={"ensure_ascii": False},
        status=200,
    )
