# core/api_urls.py
from django.urls import path

from core.api_views import (
    create_daily_run,
    get_run_out,
    health,
    create_daily_run_graph,
    generate_day_api_mirror,
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

    # Existing UI under /api/ui/
    path("ui/", ui_home, name="ui_home"),
]
