from rest_framework.authentication import BaseAuthentication


class FirebaseAuthentication(BaseAuthentication):
    """Accept the user already verified by FirebaseAuthenticationMiddleware.

    Listed first in DEFAULT_AUTHENTICATION_CLASSES so unauthenticated API
    requests get 401 with a `WWW-Authenticate: Bearer` header (not 403).
    """

    def authenticate(self, request):
        django_request = request._request
        if getattr(django_request, "firebase_authenticated", False):
            return (django_request.user, None)
        return None

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
