"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

# Docker now runs the canonical Django ASGI app under uvicorn. In debug/demo
# mode we keep Django's built-in static handler so /ui/monthly and admin assets
# still render without adding a production static stack to this repo.
if settings.DEBUG:
    application = ASGIStaticFilesHandler(django_asgi_app)
else:
    application = django_asgi_app
