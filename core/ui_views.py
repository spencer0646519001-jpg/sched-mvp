# core/ui_views.py
import json
from datetime import date

from django.shortcuts import render
from django.test.client import RequestFactory
from django.views.decorators.http import require_http_methods

from app import generate_day as gd
from core.api_views import api_monthly_export_csv, api_monthly_preview_mirror


@require_http_methods(["GET"])
def ui_home(request):
    return render(request, "ui/home.html")


@require_http_methods(["GET", "POST"])
def ui_monthly(request):
    year_month = request.POST.get("year_month") if request.method == "POST" else date.today().strftime("%Y-%m")
    language = request.POST.get("language", "ja")
    leave_requests_raw = request.POST.get("leave_requests", "{}")
    action = request.POST.get("action", "")

    context = {
        "year_month": year_month,
        "language": language or "ja",
        "leave_requests_raw": leave_requests_raw,
        "worker_names": _load_worker_names(),
        "preview_data": None,
        "error_message": "",
    }

    if request.method == "POST":
        try:
            leave_requests = json.loads(leave_requests_raw or "{}")
        except json.JSONDecodeError:
            context["error_message"] = "Invalid JSON in leave_requests. Expected dict[str, list[str]]."
            return render(request, "ui/monthly.html", context)
        context["leave_requests_raw"] = json.dumps(leave_requests, ensure_ascii=False)

        payload = {
            "year_month": year_month,
            "language": language or "ja",
            "leave_requests": leave_requests,
        }

        rf = RequestFactory()

        if action == "preview":
            internal_request = rf.post(
                "/api/monthly/preview",
                data=json.dumps(payload),
                content_type="application/json",
            )
            api_response = api_monthly_preview_mirror(internal_request)
            if api_response.status_code == 200:
                context["preview_data"] = json.loads(api_response.content.decode("utf-8"))
            else:
                try:
                    err = json.loads(api_response.content.decode("utf-8"))
                    context["error_message"] = err.get("detail") or "Preview failed."
                except json.JSONDecodeError:
                    context["error_message"] = f"Preview failed (HTTP {api_response.status_code})."

        if action == "download":
            internal_request = rf.post(
                "/api/monthly/export.csv",
                data=json.dumps(payload),
                content_type="application/json",
            )
            api_response = api_monthly_export_csv(internal_request)
            if api_response.status_code == 200:
                return api_response
            try:
                err = json.loads(api_response.content.decode("utf-8"))
                context["error_message"] = err.get("detail") or "CSV export failed."
            except json.JSONDecodeError:
                context["error_message"] = f"CSV export failed (HTTP {api_response.status_code})."

    return render(request, "ui/monthly.html", context)


def _load_worker_names():
    try:
        workers = gd.load_json("workers.json").get("people", [])
    except Exception:
        workers = []
    return [person.get("name") for person in workers if isinstance(person, dict) and person.get("name")]
