# core/api_urls.py
from django.urls import path

from core.api_views import (
    create_daily_run,
    get_run_out,
    health,
)
from core.ui_views import ui_home
from core.api_views import create_daily_run_graph

urlpatterns = [
    # API
    path("health/", health, name="api_health"),
    path("tenants/<str:tenant_name>/daily-runs/", create_daily_run, name="create_daily_run"),
    path("runs/<int:run_id>/out/", get_run_out, name="get_run_out"),

    # UI（放在 api 底下也 OK，之後可以再拆）
    path("ui/", ui_home, name="ui_home"),
]
urlpatterns = [
    #...
    path(
        "tenants/<str:tenant_name>/daily-runs-graph/",
        create_daily_run_graph,
        name="create_daily_run_graph",
    ),
]
