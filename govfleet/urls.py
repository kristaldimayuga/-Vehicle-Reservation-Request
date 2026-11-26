"""Root URL configuration for GovFleet."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from accounts.views import MeView, admin_login

from .health import health

# The Django admin has no password form: Admins sign in with Firebase.
admin.site.login = admin_login

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="reservations:calendar", permanent=False)),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("reservations/", include("reservations.urls")),
    path("api/me/", MeView.as_view(), name="api-me"),
    path("api/", include("reservations.api.urls")),
]
