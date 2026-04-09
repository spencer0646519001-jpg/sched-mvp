# core/api_urls.py
from django.urls import path

from core.api_views_daily import (
    create_daily_run,
    create_daily_run_graph,
    get_run_out,
    health,
)
from core.api_views_monthly import (
    api_monthly_export_csv,
    api_monthly_preview_mirror,
    api_monthly_refine_mirror,
    api_monthly_transcribe,
    api_monthly_workspace_save,
)

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
    path("monthly/preview", api_monthly_preview_mirror, name="api_monthly_preview_mirror"),
    path("monthly/refine", api_monthly_refine_mirror, name="api_monthly_refine_mirror"),
    path("monthly/export.csv", api_monthly_export_csv, name="api_monthly_export_csv"),
    path("monthly/workspace/save", api_monthly_workspace_save, name="api_monthly_workspace_save"),
    path("monthly/transcribe", api_monthly_transcribe, name="api_monthly_transcribe"),
]
