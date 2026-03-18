"""Compatibility exports for API view imports."""

from core.api_views_daily import (
    create_daily_run,
    create_daily_run_graph,
    generate_day_api_mirror,
    get_run_out,
    health,
    root_healthcheck,
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

__all__ = [
    "api_calendar_month_csv_mirror",
    "api_calendar_month_mirror",
    "api_month_csv_mirror",
    "api_month_mirror",
    "api_monthly_export_csv",
    "api_monthly_preview_mirror",
    "api_monthly_refine_mirror",
    "api_monthly_transcribe",
    "api_plan_create_mirror",
    "api_plan_delete_mirror",
    "api_plan_get_mirror",
    "api_plan_list_mirror",
    "api_plan_patch_apply_mirror",
    "api_plan_patch_preview_mirror",
    "api_week_csv_mirror",
    "api_week_mirror",
    "api_week_summary_mirror",
    "create_daily_run",
    "create_daily_run_graph",
    "generate_day_api_mirror",
    "get_run_out",
    "health",
    "root_healthcheck",
]
