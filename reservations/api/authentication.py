from rest_framework.authentication import SessionAuthentication


class SessionAuthentication401(SessionAuthentication):
    """Session auth that answers unauthenticated requests with 401, not 403.

    DRF only returns 401 when the first authenticator supplies a
    WWW-Authenticate header. This keeps the API contract (401 = not logged
    in, 403 = wrong role) until Firebase JWT auth replaces it.
    """

    def authenticate_header(self, request):
        return 'Session realm="api"'
