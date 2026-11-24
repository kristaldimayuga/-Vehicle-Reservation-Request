"""Presentation-layer page views (HTML only; data comes from the JSON API)."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@login_required
@ensure_csrf_cookie
def calendar_page(request):
    return render(request, "reservations/calendar.html")
