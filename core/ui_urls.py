# core/ui_urls.py
from django.urls import path
from core import ui_views

urlpatterns = [
    path("", ui_views.ui_home, name="ui_home"),
    path("monthly", ui_views.ui_monthly, name="ui_monthly"),
]
