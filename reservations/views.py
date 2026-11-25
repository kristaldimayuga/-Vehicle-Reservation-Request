"""Presentation-layer page views (HTML only; data comes from the JSON API)."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .services import VehicleReservationService


@login_required
@ensure_csrf_cookie
def calendar_page(request):
    # The calendar mirrors the server's booking horizon from this one value,
    # so the UI and the business rule cannot drift apart.
    context = {
        "max_advance_seconds": int(VehicleReservationService.MAX_ADVANCE.total_seconds()),
    }
    return render(request, "reservations/calendar.html", context)
