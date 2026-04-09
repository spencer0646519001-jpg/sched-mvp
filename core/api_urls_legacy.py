from django.urls import path

from core.api_views_daily import generate_day_api_mirror
from core.api_views_monthly import (
    api_calendar_month_csv_mirror,
    api_calendar_month_mirror,
    api_month_csv_mirror,
    api_month_mirror,
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

urlpatterns = [
    # Django HTTP compatibility/parity routes retained for review, testing, and rollback support.
    # Canonical UI stays under /ui/... rather than /api/legacy/...
    path("generate/day/<str:date>", generate_day_api_mirror, name="generate_day_api_mirror"),
    path("plan/create", api_plan_create_mirror, name="api_plan_create_mirror"),
    path("plan/patch_preview", api_plan_patch_preview_mirror, name="api_plan_patch_preview_mirror"),
    path("plan/patch_apply", api_plan_patch_apply_mirror, name="api_plan_patch_apply_mirror"),
    path("plan/get", api_plan_get_mirror, name="api_plan_get_mirror"),
    path("plan/list", api_plan_list_mirror, name="api_plan_list_mirror"),
    path("plan/delete", api_plan_delete_mirror, name="api_plan_delete_mirror"),
    path("week", api_week_mirror, name="api_week_mirror"),
    path("week/summary", api_week_summary_mirror, name="api_week_summary_mirror"),
    path("week_csv", api_week_csv_mirror, name="api_week_csv_mirror"),
    path("month", api_month_mirror, name="api_month_mirror"),
    path("month_csv", api_month_csv_mirror, name="api_month_csv_mirror"),
    path("calendar/month", api_calendar_month_mirror, name="api_calendar_month_mirror"),
    path("calendar/month_csv", api_calendar_month_csv_mirror, name="api_calendar_month_csv_mirror"),
]
