"""Project-wide middleware."""

import logging

from django.db import InterfaceError, OperationalError
from django.http import JsonResponse
from django.template.response import TemplateResponse

logger = logging.getLogger("govfleet")

RETRY_AFTER_SECONDS = 30


class DatabaseUnavailableMiddleware:
    """Turn database connectivity failures into a clean 503 response.

    API views already do this through the DRF exception handler; this covers
    everything else (HTML pages, login, admin) so users never see a stack
    trace or Django's debug page when PostgreSQL is down.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (OperationalError, InterfaceError)):
            return None

        logger.error("Database unavailable for %s %s: %s", request.method, request.path, exception)
        if request.path.startswith("/api/") or "application/json" in request.headers.get("Accept", ""):
            response = JsonResponse(
                {
                    "detail": "The service is temporarily unavailable. Please try again shortly.",
                    "code": "service_unavailable",
                },
                status=503,
            )
        else:
            response = TemplateResponse(request, "503.html", status=503)
            response.render()
        response["Retry-After"] = str(RETRY_AFTER_SECONDS)
        return response
