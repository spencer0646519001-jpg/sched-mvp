"""
Server-rendered Django demo views.

Reviewer notes:
- `/ui/monthly` is the main monthly demo/review surface today.
- The page does not call an external frontend app; it builds internal Django
  requests and reuses the monthly API views in-process.
- "Apply" updates the current request-scoped working state used for export.
- "Save" persists the current monthly workspace state for later restoration.
- Monthly helper names now reuse the canonical roster metadata read-path.
"""

# core/ui_views.py
import json
from datetime import date
from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.test.client import RequestFactory
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from app.infra.monthly_scheduling_inputs import (
    MONTHLY_DEMO_TENANT_NAME,
    load_monthly_roster_metadata,
)
from core import monthly_workspace_persistence, monthly_workspace_service
from core.api_views_monthly import (
    api_monthly_export_csv,
    api_monthly_preview_mirror,
    api_monthly_refine_mirror,
    api_monthly_workspace_save,
)


MONTHLY_UI_ENGLISH_TEXT = {
    "page_title": "Monthly Scheduling Workspace",
    "hero_desc": "Preview and export use the same payload:",
    "controls": "Controls",
    "year_month": "Year Month",
    "leave_requests": "Leave Requests",
    "leave_help": "Select person + date, then add. Each date becomes OFF in preview/export.",
    "person": "Person",
    "date": "Date",
    "add_leave": "Add Leave",
    "no_leave_selected": "No leave dates selected yet.",
    "actions": "Actions",
    "preview": "Preview",
    "download_csv": "Download CSV",
    "refine_title": "Refine Schedule",
    "refine_help": "Input natural-language schedule adjustments, then preview diff before apply/save.",
    "refine_text_label": "Refine Text",
    "refine_preview": "Refine Preview",
    "apply_save": "Apply / Save",
    "diff_preview": "Diff Preview",
    "no_diff": "No changes detected.",
    "no_refine_result_yet": "No refine result yet",
    "refine_parse_failed": "Refine parse failed",
    "apply_succeeded": "Apply succeeded",
    "refine_failed": "Refine preview failed.",
    "request_error": "Request Error",
    "weekly_rest_warnings": "Weekly Rest Warnings",
    "weekly_ok": "OK: weekly rest checks passed.",
    "run_preview_hint": "Run Preview to evaluate weekly rest constraints.",
    "explain_trace": "Explain / Decision Trace",
    "summary_with_warnings_prefix": "Summary:",
    "summary_with_warnings_suffix": "warning(s). People with <2 OFF days in a full ISO week are highlighted.",
    "summary_no_warnings": "Summary: no weekly rest warnings for full ISO weeks in this preview.",
    "summary_waiting_preview": "Summary will appear after preview.",
    "explain_date": "Explain Date",
    "generate_explanation": "Generate Explanation",
    "explain_optional_endpoint": "Optional integration endpoint",
    "explain_unavailable_until_generated": "Explain currently unavailable until generated.",
    "people_grid": "People Grid",
    "name": "Name",
    "role_chef": "chef",
    "role_staff": "staff",
    "role_unknown": "unknown",
    "invalid_leave_json": "Invalid JSON in leave_requests. Expected dict[str, list[str]].",
    "preview_failed": "Preview failed.",
    "csv_export_failed": "CSV export failed.",
    "explain_choose_valid_date": "Explain currently unavailable: choose a valid date.",
    "generating_explanation": "Generating explanation...",
    "explanation_generated_for": "Explanation generated for ",
    "explain_unavailable": "Explain currently unavailable.",
}


MONTHLY_UI_TRANSIENT_STATE_SESSION_KEY = "ui_monthly_transient_state"
MONTHLY_UI_NOTICE_SESSION_KEY = "ui_monthly_notice"
MONTHLY_UI_TRANSIENT_STATE_FIELDS = (
    "leave_requests_raw",
    "refine_text",
    "refine_preview_json",
    "working_state_json",
    "preview_data",
    "refine_data",
    "refine_applied",
    "apply_notice",
    "workspace_notice",
    "error_message",
)

MONTHLY_VOICE_ENGLISH_TEXT = {
    "voice_input": "Voice Input",
    "listening": "Listening...",
    "stop": "Stop",
    "voice_unsupported": "Voice input not supported in this browser.",
    "voice_failed": "Voice recognition failed.",
    "voice_status_idle": "Idle",
    "voice_status_listening": "Listening",
    "voice_status_transcribing": "Transcribing",
    "voice_status_unsupported": "Unsupported",
    "voice_status_error": "Error",
    "voice_transcribing": "Transcribing audio...",
    "voice_transcribe_failed_fallback": "Transcription failed. Falling back to browser speech recognition.",
    "voice_recording_start_failed": "Unable to start recording. Falling back to browser speech recognition.",
    "voice_recording_unsupported_fallback": "Audio recording unsupported. Falling back to browser speech recognition.",
}

def _voice_translation_pack() -> dict:
    return dict(MONTHLY_VOICE_ENGLISH_TEXT)


def _translation_pack() -> dict:
    return {"t": dict(MONTHLY_UI_ENGLISH_TEXT)}


def _parse_monthly_working_state(raw_json: str) -> dict:
    try:
        parsed = json.loads(raw_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _monthly_redirect_response(*, year_month: str):
    query = {"year_month": year_month}
    return redirect(f"{reverse('ui_monthly')}?{urlencode(query)}")


def _stash_monthly_ui_transient_state(request, context: dict) -> None:
    request.session[MONTHLY_UI_TRANSIENT_STATE_SESSION_KEY] = {
        "year_month": str(context.get("year_month") or ""),
        "state": {
            key: context.get(key)
            for key in MONTHLY_UI_TRANSIENT_STATE_FIELDS
        },
    }


def _consume_monthly_ui_transient_state(request, *, year_month: str) -> dict | None:
    payload = request.session.pop(MONTHLY_UI_TRANSIENT_STATE_SESSION_KEY, None)
    if not isinstance(payload, dict):
        return None
    if str(payload.get("year_month") or "") != str(year_month or ""):
        return None
    state = payload.get("state")
    return state if isinstance(state, dict) else None


def _apply_monthly_ui_transient_state(context: dict, state: dict) -> None:
    for key in MONTHLY_UI_TRANSIENT_STATE_FIELDS:
        if key in state:
            context[key] = state.get(key)


def _stash_monthly_ui_notice(request, *, year_month: str, message: str) -> None:
    request.session[MONTHLY_UI_NOTICE_SESSION_KEY] = {
        "year_month": str(year_month or ""),
        "message": str(message or ""),
    }


def _consume_monthly_ui_notice(request, *, year_month: str) -> str:
    payload = request.session.pop(MONTHLY_UI_NOTICE_SESSION_KEY, None)
    if not isinstance(payload, dict):
        return ""
    if str(payload.get("year_month") or "") != str(year_month or ""):
        return ""
    return str(payload.get("message") or "")


def _store_monthly_working_state(context: dict, *, people_grid, weekly_rest_warnings=None, warnings=None) -> None:
    state = monthly_workspace_service.build_monthly_working_state(
        people_grid=people_grid,
        weekly_rest_warnings=weekly_rest_warnings,
        warnings=warnings,
    )
    context["working_state_json"] = json.dumps(state, ensure_ascii=False) if state else ""


def _build_preview_data_from_working_state(
    *,
    year_month: str,
    leave_requests: dict,
    working_state: dict,
) -> dict:
    preview_data = {
        "people_grid": working_state.get("people_grid", {}),
        "weekly_rest_warnings": list(working_state.get("weekly_rest_warnings", [])),
        "warnings": list(working_state.get("warnings", [])),
    }
    rf = RequestFactory()
    internal_request = rf.post(
        "/api/monthly/preview",
        data=json.dumps(
            {
                "year_month": year_month,
                "leave_requests": leave_requests,
            }
        ),
        content_type="application/json",
    )
    api_response = api_monthly_preview_mirror(internal_request)
    if api_response.status_code != 200:
        return preview_data

    try:
        base_preview = json.loads(api_response.content.decode("utf-8"))
    except json.JSONDecodeError:
        return preview_data
    if not isinstance(base_preview, dict):
        return preview_data

    merged_preview = dict(base_preview)
    merged_preview["people_grid"] = preview_data["people_grid"]
    merged_preview["weekly_rest_warnings"] = preview_data["weekly_rest_warnings"]
    merged_preview["warnings"] = preview_data["warnings"]
    return merged_preview


@require_http_methods(["GET"])
def ui_home(request):
    return render(request, "ui/home.html")


@require_http_methods(["GET", "POST"])
def ui_monthly(request):
    """Drive the current monthly preview/refine/export demo from one Django page."""
    year_month = (
        request.POST.get("year_month")
        if request.method == "POST"
        else request.GET.get("year_month", date.today().strftime("%Y-%m"))
    )
    saved_workspace = None
    transient_state = None
    workspace_notice = ""
    if request.method == "GET":
        saved_workspace = monthly_workspace_persistence.load_monthly_workspace(
            tenant_name=MONTHLY_DEMO_TENANT_NAME,
            year_month=year_month,
        )
        transient_state = _consume_monthly_ui_transient_state(request, year_month=year_month)
        workspace_notice = _consume_monthly_ui_notice(request, year_month=year_month)

    leave_requests_raw = (
        request.POST.get("leave_requests", "{}")
        if request.method == "POST"
        else (
            str((transient_state or {}).get("leave_requests_raw"))
            if transient_state is not None and "leave_requests_raw" in transient_state
            else json.dumps((saved_workspace or {}).get("leave_requests", {}), ensure_ascii=False)
        )
    )
    refine_text = (
        request.POST.get("refine_text", "")
        if request.method == "POST"
        else str((transient_state or {}).get("refine_text") or "")
    )
    refine_preview_raw = (
        request.POST.get("refine_preview_json", "")
        if request.method == "POST"
        else str((transient_state or {}).get("refine_preview_json") or "")
    )
    working_state_raw = (
        request.POST.get("working_state_json", "")
        if request.method == "POST"
        else (
            str((transient_state or {}).get("working_state_json") or "")
            if transient_state is not None and "working_state_json" in transient_state
            else (
                json.dumps((saved_workspace or {}).get("working_state", {}), ensure_ascii=False)
                if saved_workspace is not None
                else ""
            )
        )
    )
    action = request.POST.get("action", "")

    tr = _translation_pack()
    t_pack = dict(tr["t"])
    t_pack.setdefault("refine_title", "Refine Schedule")
    t_pack.setdefault("refine_help", "Input natural-language schedule adjustments, then preview diff before apply/save.")
    t_pack.setdefault("refine_semantics_help", "Input natural-language schedule adjustments, preview the candidate diff, then Apply it to update the working state. Save persists the current workspace.")
    t_pack.setdefault("refine_text_label", "Refine Text")
    t_pack.setdefault("refine_preview", "Refine Preview")
    t_pack.setdefault("action_semantics", "Preview rebuilds from canonical inputs. Refine Preview shows candidate changes. Apply updates current working state. Save persists the current state used by Export CSV.")
    t_pack.setdefault("apply_label", "Apply")
    t_pack.setdefault("apply_disabled_help", "Run Refine Preview before Apply.")
    t_pack.setdefault("save_label", "Save")
    t_pack.setdefault("save_help", "Save persists the current working state for this month.")
    t_pack.setdefault("workspace_saved_notice", "Saved current workspace.")
    t_pack.setdefault("workspace_restored_notice", "Restored saved workspace for ")
    t_pack.setdefault("save_requires_workspace", "Save requires a current workspace. Run Preview or Apply first.")
    t_pack.setdefault("save_failed", "Unable to save current workspace.")
    t_pack.setdefault("diff_preview", "Diff Preview")
    t_pack.setdefault("shift_legend", "Shift Legend")
    t_pack.setdefault("refine_candidate_notice", "Showing a refine candidate only. Export CSV still uses the current working state until you Apply.")
    t_pack.setdefault("refine_applied_notice", "This refine result is applied to the current working state used by Export CSV.")
    t_pack.setdefault("apply_notice", "Applied to current working state.")
    t_pack.setdefault("apply_succeeded", "Applied to current working state.")
    t_pack.setdefault("apply_done", t_pack["apply_succeeded"])
    t_pack.setdefault("refine_failed", "Refine preview failed.")
    t_pack.setdefault("refine_parse_failed", "Refine parse failed")
    t_pack.setdefault("no_diff", "No changes detected.")
    t_pack.setdefault("no_refine_result_yet", "No refine result yet")
    for key, value in _voice_translation_pack().items():
        t_pack.setdefault(key, value)
    t_pack["export_csv"] = "Export CSV"

    context = {
        "year_month": year_month,
        "leave_requests_raw": leave_requests_raw,
        "refine_text": refine_text,
        "refine_preview_json": refine_preview_raw,
        "working_state_json": working_state_raw,
        "worker_names": _load_worker_names(),
        "preview_data": None,
        "refine_data": None,
        "refine_applied": False,
        "apply_notice": "",
        "workspace_notice": workspace_notice,
        "error_message": "",
        "t": t_pack,
        "ui_strings_json": json.dumps(t_pack, ensure_ascii=False),
    }

    if request.method == "GET" and transient_state is not None:
        _apply_monthly_ui_transient_state(context, transient_state)
    elif request.method == "GET" and saved_workspace is not None:
        leave_requests = dict(saved_workspace.get("leave_requests") or {})
        working_state = dict(saved_workspace.get("working_state") or {})
        context["leave_requests_raw"] = json.dumps(leave_requests, ensure_ascii=False)
        context["working_state_json"] = json.dumps(working_state, ensure_ascii=False)
        context["preview_data"] = _build_preview_data_from_working_state(
            year_month=year_month,
            leave_requests=leave_requests,
            working_state=working_state,
        )
        if not context["workspace_notice"]:
            context["workspace_notice"] = f"{context['t']['workspace_restored_notice']}{year_month}."

    if request.method == "POST":
        try:
            leave_requests = json.loads(leave_requests_raw or "{}")
        except json.JSONDecodeError:
            context["error_message"] = context["t"]["invalid_leave_json"]
            return render(request, "ui/monthly.html", context)
        context["leave_requests_raw"] = json.dumps(leave_requests, ensure_ascii=False)

        payload = {
            "year_month": year_month,
            "leave_requests": leave_requests,
        }

        # The demo UI reuses the Django monthly API views directly so reviewers
        # can trace one request path without a separate frontend runtime.
        rf = RequestFactory()

        if action == "preview":
            internal_request = rf.post(
                "/api/monthly/preview",
                data=json.dumps(payload),
                content_type="application/json",
            )
            api_response = api_monthly_preview_mirror(internal_request)
            if api_response.status_code == 200:
                preview_data = json.loads(api_response.content.decode("utf-8"))
                context["preview_data"] = preview_data
                context["refine_data"] = None
                context["refine_preview_json"] = ""
                context["refine_applied"] = False
                _store_monthly_working_state(
                    context,
                    people_grid=preview_data.get("people_grid"),
                    weekly_rest_warnings=preview_data.get("weekly_rest_warnings", []),
                    warnings=preview_data.get("warnings", []),
                )
                _stash_monthly_ui_transient_state(request, context)
                return _monthly_redirect_response(year_month=year_month)
            else:
                try:
                    err = json.loads(api_response.content.decode("utf-8"))
                    context["error_message"] = err.get("detail") or context["t"]["preview_failed"]
                except json.JSONDecodeError:
                    context["error_message"] = f"Preview failed (HTTP {api_response.status_code})."

        if action == "download":
            export_payload = dict(payload)
            working_state = _parse_monthly_working_state(working_state_raw)
            working_people_grid = working_state.get("people_grid")
            if isinstance(working_people_grid, dict):
                export_payload["working_people_grid"] = working_people_grid
            internal_request = rf.post(
                "/api/monthly/export.csv",
                data=json.dumps(export_payload),
                content_type="application/json",
            )
            api_response = api_monthly_export_csv(internal_request)
            if api_response.status_code == 200:
                return api_response
            try:
                err = json.loads(api_response.content.decode("utf-8"))
                context["error_message"] = err.get("detail") or context["t"]["csv_export_failed"]
            except json.JSONDecodeError:
                context["error_message"] = f"CSV export failed (HTTP {api_response.status_code})."

        if action == "refine_preview":
            refine_payload = dict(payload)
            refine_payload["refine_text"] = refine_text
            working_state = _parse_monthly_working_state(working_state_raw)
            if isinstance(working_state.get("people_grid"), dict):
                refine_payload["working_state"] = working_state
            internal_request = rf.post(
                "/api/monthly/refine",
                data=json.dumps(refine_payload),
                content_type="application/json",
            )
            api_response = api_monthly_refine_mirror(internal_request)
            if api_response.status_code == 200:
                refine_data = json.loads(api_response.content.decode("utf-8"))
                context["refine_data"] = refine_data
                context["refine_preview_json"] = json.dumps(refine_data, ensure_ascii=False)
                context["refine_applied"] = False
                parse_errors = refine_data.get("parse_errors") if isinstance(refine_data, dict) else None
                if isinstance(parse_errors, list) and parse_errors:
                    messages = [
                        str(item.get("message", "")).strip()
                        for item in parse_errors
                        if isinstance(item, dict) and str(item.get("message", "")).strip()
                    ]
                    message = "; ".join(messages[:3]).strip()
                    if message:
                        context["error_message"] = f"{context['t']['refine_parse_failed']}: {message}"
                    else:
                        context["error_message"] = context["t"]["refine_parse_failed"]
                _stash_monthly_ui_transient_state(request, context)
                return _monthly_redirect_response(year_month=year_month)
            else:
                try:
                    err = json.loads(api_response.content.decode("utf-8"))
                    parse_errors = err.get("parse_errors") if isinstance(err, dict) else None
                    if isinstance(parse_errors, list) and parse_errors:
                        messages = [
                            str(item.get("message", "")).strip()
                            for item in parse_errors
                            if isinstance(item, dict) and str(item.get("message", "")).strip()
                        ]
                        message = "; ".join(messages[:3]).strip()
                        if message:
                            context["error_message"] = f"{context['t']['refine_parse_failed']}: {message}"
                        else:
                            context["error_message"] = context["t"]["refine_parse_failed"]
                    else:
                        context["error_message"] = err.get("detail") or context["t"]["refine_failed"]
                except json.JSONDecodeError:
                    context["error_message"] = f"Refine failed (HTTP {api_response.status_code})."

        if action == "apply_refine":
            try:
                refine_data = json.loads(refine_preview_raw or "{}")
            except json.JSONDecodeError:
                refine_data = {}

            # This is a UI-only apply step: keep the refined preview visible and
            # exportable in the request-scoped working state, but do not persist
            # a monthly plan.
            preview_people_grid = refine_data.get("preview_people_grid")
            if isinstance(preview_people_grid, dict):
                context["preview_data"] = {
                    "people_grid": preview_people_grid,
                    "weekly_rest_warnings": refine_data.get("weekly_rest_warnings", []),
                    "warnings": refine_data.get("warnings", []),
                }
                context["refine_data"] = refine_data
                context["refine_preview_json"] = json.dumps(refine_data, ensure_ascii=False)
                context["refine_applied"] = True
                _store_monthly_working_state(
                    context,
                    people_grid=preview_people_grid,
                    weekly_rest_warnings=refine_data.get("weekly_rest_warnings", []),
                    warnings=refine_data.get("warnings", []),
                )
                context["apply_notice"] = context["t"]["apply_notice"]
                _stash_monthly_ui_transient_state(request, context)
                return _monthly_redirect_response(year_month=year_month)
            else:
                context["error_message"] = context["t"]["refine_failed"]

        if action == "save":
            working_state = _parse_monthly_working_state(working_state_raw)
            if not isinstance(working_state.get("people_grid"), dict):
                context["error_message"] = context["t"]["save_requires_workspace"]
            else:
                context["preview_data"] = _build_preview_data_from_working_state(
                    year_month=year_month,
                    leave_requests=leave_requests,
                    working_state=working_state,
                )
                save_payload = dict(payload)
                save_payload["working_state"] = working_state
                internal_request = rf.post(
                    "/api/monthly/workspace/save",
                    data=json.dumps(save_payload),
                    content_type="application/json",
                )
                api_response = api_monthly_workspace_save(internal_request)
                if api_response.status_code == 200:
                    try:
                        save_result = json.loads(api_response.content.decode("utf-8"))
                    except json.JSONDecodeError:
                        save_result = {}
                    workspace = save_result.get("workspace") if isinstance(save_result, dict) else {}
                    if isinstance(workspace, dict):
                        saved_leave_requests = dict(workspace.get("leave_requests") or leave_requests)
                        saved_working_state = dict(workspace.get("working_state") or working_state)
                        context["leave_requests_raw"] = json.dumps(saved_leave_requests, ensure_ascii=False)
                        context["working_state_json"] = json.dumps(saved_working_state, ensure_ascii=False)
                        context["preview_data"] = _build_preview_data_from_working_state(
                            year_month=year_month,
                            leave_requests=saved_leave_requests,
                            working_state=saved_working_state,
                        )
                    context["workspace_notice"] = context["t"]["workspace_saved_notice"]
                    _stash_monthly_ui_notice(
                        request,
                        year_month=year_month,
                        message=context["workspace_notice"],
                    )
                    return _monthly_redirect_response(year_month=year_month)
                else:
                    try:
                        err = json.loads(api_response.content.decode("utf-8"))
                        context["error_message"] = err.get("detail") or context["t"]["save_failed"]
                    except json.JSONDecodeError:
                        context["error_message"] = f"Save failed (HTTP {api_response.status_code})."

    return render(request, "ui/monthly.html", context)


def _load_worker_names():
    try:
        roster_metadata = load_monthly_roster_metadata(tenant_name=MONTHLY_DEMO_TENANT_NAME)
    except Exception:
        return []
    return list(roster_metadata.ordered_names)
