"""Domain exceptions for authentication. Views/middleware map them to HTTP."""


class AccountError(Exception):
    status = 401
    code = "authentication_failed"
    default_message = "Authentication failed."

    def __init__(self, message=None):
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidToken(AccountError):
    """Missing, malformed, expired, revoked, or forged Firebase ID token (401)."""

    code = "invalid_token"
    default_message = "Your sign-in is invalid or has expired. Please sign in again."


class StaleSignIn(AccountError):
    """Token too old to start a new session; the user must sign in again (401)."""

    code = "recent_sign_in_required"
    default_message = "Please sign in again."


class EmailNotVerified(AccountError):
    status = 403
    code = "email_not_verified"
    default_message = "Please verify your email address before signing in."


class EmailNotAllowed(AccountError):
    status = 403
    code = "email_not_allowed"
    default_message = (
        "Use your agency email in the form firstnamelastname@agency.gov.ph."
    )


class AdminNotApproved(AccountError):
    status = 403
    code = "admin_not_approved"
    default_message = "This admin account has not been approved."


class AccountDisabled(AccountError):
    status = 403
    code = "account_disabled"
    default_message = "This account has been disabled."


class AuthServiceUnavailable(AccountError):
    """Firebase could not be reached or is not configured (503)."""

    status = 503
    code = "auth_unavailable"
    default_message = "Sign-in is temporarily unavailable. Please try again shortly."
