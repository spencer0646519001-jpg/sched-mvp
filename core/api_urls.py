# core/api_urls.py
from django.urls import path

from core.api_views_daily import (
    create_daily_run,
    create_daily_run_graph,
    generate_day_api_mirror,
    get_run_out,
    health,
)
from core.api_views_monthly import (
    api_calendar_month_csv_mirror,
    api_calendar_month_mirror,
    api_month_csv_mirror,
    api_month_mirror,
    api_monthly_export_csv,
    api_monthly_preview_mirror,
    api_monthly_refine_mirror,
    api_monthly_transcribe,
    api_monthly_workspace_save,
    api_week_csv_mirror,
    api_week_mirror,
    api_week_summary_mirror,
)
from core.api_views_plan import (
    api_plan_create_mirror,
    api_plan_delete_mirror,
    api_plan_get_mirror,
    api_plan_list_mirror,
    api_plan_patch_apply_mirror,
    api_plan_patch_preview_mirror,
)
from core.ui_views import ui_home

urlpatterns = [
    # Canonical Django runtime endpoints used by the current backend.
    path("health/", health, name="api_health"),
    path("tenants/<str:tenant_name>/daily-runs/", create_daily_run, name="create_daily_run"),
    path("runs/<int:run_id>/out/", get_run_out, name="get_run_out"),
    path(
        "tenants/<str:tenant_name>/daily-runs-graph/",
        create_daily_run_graph,
        name="create_daily_run_graph",
    ),

    # Migration-era mirror kept for older route parity during the runtime shift.
    path("generate/day/<str:date>", generate_day_api_mirror, name="generate_day_api_mirror"),

    # Migration/parity plan endpoints. These are not the clean canonical shape.
    path("plan/create", api_plan_create_mirror, name="api_plan_create_mirror"),
    path("plan/patch_preview", api_plan_patch_preview_mirror, name="api_plan_patch_preview_mirror"),
    path("plan/patch_apply", api_plan_patch_apply_mirror, name="api_plan_patch_apply_mirror"),
    path("plan/get", api_plan_get_mirror, name="api_plan_get_mirror"),
    path("plan/list", api_plan_list_mirror, name="api_plan_list_mirror"),
    path("plan/delete", api_plan_delete_mirror, name="api_plan_delete_mirror"),

    # Current monthly demo flow under Django, alongside older parity-style routes.
    path("week", api_week_mirror, name="api_week_mirror"),
    path("week/summary", api_week_summary_mirror, name="api_week_summary_mirror"),
    path("week_csv", api_week_csv_mirror, name="api_week_csv_mirror"),
    path("month", api_month_mirror, name="api_month_mirror"),
    path("month_csv", api_month_csv_mirror, name="api_month_csv_mirror"),
    path("calendar/month", api_calendar_month_mirror, name="api_calendar_month_mirror"),
    path("calendar/month_csv", api_calendar_month_csv_mirror, name="api_calendar_month_csv_mirror"),
    path("monthly/preview", api_monthly_preview_mirror, name="api_monthly_preview_mirror"),
    path("monthly/refine", api_monthly_refine_mirror, name="api_monthly_refine_mirror"),
    path("monthly/export.csv", api_monthly_export_csv, name="api_monthly_export_csv"),
    path("monthly/workspace/save", api_monthly_workspace_save, name="api_monthly_workspace_save"),
    path("monthly/transcribe", api_monthly_transcribe, name="api_monthly_transcribe"),

    # Existing UI under /api/ui/
    path("ui/", ui_home, name="ui_home"),
]
