"""Firebase JWT middleware.

For requests carrying `Authorization: Bearer <Firebase ID token>`, verify the
token with firebase-admin, map the UID to the local shadow user (with its
RBAC role) and set `request.user`. Invalid tokens are rejected here with a
JSON 401/403/503 and never reach a view.

Requests without a Bearer header fall through to the normal Django session
(established once by accounts.views.session_login after the same
verification).
"""

from django.http import JsonResponse

from .services.account_service import AccountService
from .services.exceptions import AccountError


class FirebaseAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer":
            try:
                user = AccountService.authenticate_token(token.strip())
            except AccountError as exc:
                response = JsonResponse({"detail": exc.message, "code": exc.code}, status=exc.status)
                if exc.status == 401:
                    response["WWW-Authenticate"] = 'Bearer realm="api"'
                return response
            request.user = user
            request.firebase_authenticated = True
            # Token auth is not cookie-based, so CSRF does not apply.
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)
