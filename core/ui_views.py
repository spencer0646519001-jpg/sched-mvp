# core/ui_views.py
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

@require_http_methods(["GET"])
def ui_home(request):
    return render(request, "ui/home.html")
