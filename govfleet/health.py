"""Liveness/readiness probe: GET /health/.

Unauthenticated on purpose (for uptime monitors and load balancers), so it
reports only "ok"/"unavailable" and never error details.
"""

import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger("govfleet.health")


def database_is_reachable():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        logger.warning("Health check: database unreachable: %s", exc)
        return False
    return True


@never_cache
@require_GET
def health(request):
    db_ok = database_is_reachable()
    return JsonResponse(
        {"status": "ok" if db_ok else "unavailable", "database": "ok" if db_ok else "unavailable"},
        status=200 if db_ok else 503,
    )
