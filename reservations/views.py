"""Presentation-layer page views (HTML only; data comes from the JSON API)."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from accounts.services.account_service import is_staff_role, role_of

from .services import VehicleReservationService


@login_required
@ensure_csrf_cookie
def calendar_page(request):
    context = {
        # The calendar mirrors the server's booking horizon from this one
        # value, so the UI and the business rule cannot drift apart.
        "max_advance_seconds": int(VehicleReservationService.MAX_ADVANCE.total_seconds()),
        # Only changes what the page shows; the API enforces visibility.
        "role": role_of(request.user),
        "sees_all": is_staff_role(request.user),
    }
    return render(request, "reservations/calendar.html", context)
