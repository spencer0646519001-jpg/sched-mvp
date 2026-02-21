# core/api_urls.py
from django.urls import path

from core.api_views import (
    create_daily_run,
    get_run_out,
    health,
    create_daily_run_graph,
    generate_day_api_mirror,
    api_plan_create_mirror,
    api_plan_patch_preview_mirror,
    api_plan_patch_apply_mirror,
    api_plan_get_mirror,
    api_plan_list_mirror,
    api_plan_delete_mirror,
    api_week_mirror,
    api_week_summary_mirror,
    api_week_csv_mirror,
    api_month_mirror,
    api_month_csv_mirror,
    api_calendar_month_mirror,
    api_calendar_month_csv_mirror,
    api_monthly_preview_mirror,
    api_monthly_export_csv,
)
from core.ui_views import ui_home

urlpatterns = [
    # Existing API
    path("health/", health, name="api_health"),
    path("tenants/<str:tenant_name>/daily-runs/", create_daily_run, name="create_daily_run"),
    path("runs/<int:run_id>/out/", get_run_out, name="get_run_out"),
    path(
        "tenants/<str:tenant_name>/daily-runs-graph/",
        create_daily_run_graph,
        name="create_daily_run_graph",
    ),

    # Minimal FastAPI mirror in Django (D1 scope)
    path("generate/day/<str:date>", generate_day_api_mirror, name="generate_day_api_mirror"),

    # plan* endpoints parity mirror (PR-D2)
    path("plan/create", api_plan_create_mirror, name="api_plan_create_mirror"),
    path("plan/patch_preview", api_plan_patch_preview_mirror, name="api_plan_patch_preview_mirror"),
    path("plan/patch_apply", api_plan_patch_apply_mirror, name="api_plan_patch_apply_mirror"),
    path("plan/get", api_plan_get_mirror, name="api_plan_get_mirror"),
    path("plan/list", api_plan_list_mirror, name="api_plan_list_mirror"),
    path("plan/delete", api_plan_delete_mirror, name="api_plan_delete_mirror"),

    # week/month/calendar endpoints parity mirror (PR-D1)
    path("week", api_week_mirror, name="api_week_mirror"),
    path("week/summary", api_week_summary_mirror, name="api_week_summary_mirror"),
    path("week_csv", api_week_csv_mirror, name="api_week_csv_mirror"),
    path("month", api_month_mirror, name="api_month_mirror"),
    path("month_csv", api_month_csv_mirror, name="api_month_csv_mirror"),
    path("calendar/month", api_calendar_month_mirror, name="api_calendar_month_mirror"),
    path("calendar/month_csv", api_calendar_month_csv_mirror, name="api_calendar_month_csv_mirror"),
    path("monthly/preview", api_monthly_preview_mirror, name="api_monthly_preview_mirror"),
    path("monthly/export.csv", api_monthly_export_csv, name="api_monthly_export_csv"),

    # Existing UI under /api/ui/
    path("ui/", ui_home, name="ui_home"),
]
