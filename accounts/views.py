"""Sign-in pages and endpoints. Verification and role rules live in services/."""

import logging

from django.conf import settings
from django.contrib.auth import login, logout
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .services.account_service import AccountService, role_of
from .services.exceptions import AccountError

logger = logging.getLogger("govfleet.auth")

SESSION_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return value
    return resolve_url(settings.LOGIN_REDIRECT_URL)


@ensure_csrf_cookie
def login_page(request):
    next_url = _safe_next(request, request.GET.get("next"))
    if request.user.is_authenticated and "signed_out" not in request.GET:
        return HttpResponseRedirect(next_url)
    context = {
        "next_url": next_url,
        "firebase_config": settings.FIREBASE_WEB_CONFIG,
        "firebase_configured": all(settings.FIREBASE_WEB_CONFIG.values()),
    }
    return render(request, "accounts/login.html", context)


class SessionLoginView(APIView):
    """POST /accounts/session/ {"idToken": "..."} -> Django session.

    The token must be fresh (signed in within the last 5 minutes). CSRF is
    enforced to prevent login CSRF. Rate-limited per client.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_session"

    def post(self, request):
        SessionAuthentication().enforce_csrf(request)  # raises 403 on failure

        token = request.data.get("idToken") if isinstance(request.data, dict) else None
        if not isinstance(token, str) or not token:
            return Response(
                {"idToken": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            user = AccountService.authenticate_token(token, require_recent_sign_in=True)
        except AccountError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)

        login(request._request, user, backend=SESSION_BACKEND)
        next_url = _safe_next(request._request, request.data.get("next"))
        return Response({"redirect": next_url, "role": role_of(user)})


@require_POST
def logout_view(request):
    logout(request)
    # The login page also signs the browser out of Firebase when it sees this flag.
    return redirect(f"{reverse('login')}?signed_out=1")


class MeView(APIView):
    """GET /api/me/ — the signed-in account and its role."""

    def get(self, request):
        user = request.user
        profile = getattr(user, "profile", None)
        return Response(
            {
                "email": user.email,
                "role": role_of(user),
                "agency": profile.agency if profile else "",
                "display_name": profile.display_name if profile else "",
            }
        )


def admin_login(request, extra_context=None):
    """Replaces the Django admin's password form: sign in with Firebase instead."""
    if request.user.is_authenticated:
        # Signed in, but not an Admin.
        raise PermissionDenied
    return redirect(f"{reverse('login')}?next={request.get_full_path()}")
