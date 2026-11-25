"""DRF exception handler: every API error is JSON, never a stack trace.

- DRF's own exceptions (validation, auth, throttling, ...) keep their
  normal responses.
- Database connectivity failures become 503 Service Unavailable so the
  client can tell "try again later" apart from a bug.
- Anything else unexpected becomes a generic 500 JSON body.

Details are written to the server log only.
"""

import logging

from django.db import DatabaseError, InterfaceError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

logger = logging.getLogger("govfleet.api")

RETRY_AFTER_SECONDS = 30

DB_UNAVAILABLE_ERRORS = (OperationalError, InterfaceError)


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    view = context.get("view")
    view_name = type(view).__name__ if view is not None else "unknown"
    set_rollback()

    if isinstance(exc, DB_UNAVAILABLE_ERRORS):
        logger.error("Database unavailable in %s: %s", view_name, exc, exc_info=exc)
        return Response(
            {
                "detail": "The service is temporarily unavailable. Please try again shortly.",
                "code": "service_unavailable",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )

    if isinstance(exc, DatabaseError):
        logger.error("Database error in %s", view_name, exc_info=exc)
    else:
        logger.exception("Unhandled error in %s", view_name, exc_info=exc)
    return Response(
        {"detail": "An unexpected error occurred.", "code": "server_error"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
