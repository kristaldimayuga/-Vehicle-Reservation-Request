"""Thin wrapper around the firebase-admin SDK.

The only module that talks to Firebase. Everything else calls these
functions, so tests can patch them and CI needs no real credentials.
SDK errors are translated into domain exceptions (services/exceptions.py).
"""

import logging
import secrets
import threading

import firebase_admin
from django.conf import settings
from firebase_admin import auth, credentials
from firebase_admin import exceptions as fb_exceptions

from .services.exceptions import AuthServiceUnavailable, InvalidToken

logger = logging.getLogger("govfleet.auth")

APP_NAME = "govfleet"
_init_lock = threading.Lock()


def _app():
    """Initialise the Admin SDK once, from the service-account key path in settings."""
    try:
        return firebase_admin.get_app(APP_NAME)
    except ValueError:
        pass
    with _init_lock:
        try:
            return firebase_admin.get_app(APP_NAME)
        except ValueError:
            path = settings.FIREBASE_CREDENTIALS
            if not path:
                logger.error("FIREBASE_CREDENTIALS is not set; Firebase sign-in is unavailable.")
                raise AuthServiceUnavailable()
            try:
                cred = credentials.Certificate(path)
            except (OSError, ValueError) as exc:
                # Never log the key contents; the path is enough to debug.
                logger.error("Cannot load Firebase service-account key from %s: %s", path, type(exc).__name__)
                raise AuthServiceUnavailable() from exc
            return firebase_admin.initialize_app(
                cred, {"projectId": settings.FIREBASE_PROJECT_ID or cred.project_id}, name=APP_NAME
            )


def verify_id_token(id_token):
    """Verify signature, expiry, audience, issuer and revocation. Returns the claims."""
    if not id_token or not isinstance(id_token, str):
        raise InvalidToken()
    app = _app()
    try:
        return auth.verify_id_token(id_token, app=app, check_revoked=True, clock_skew_seconds=10)
    except (auth.InvalidIdTokenError, auth.UserDisabledError) as exc:
        # Includes ExpiredIdTokenError and RevokedIdTokenError (subclasses).
        logger.info("Rejected Firebase ID token: %s", type(exc).__name__)
        raise InvalidToken() from exc
    except auth.CertificateFetchError as exc:
        logger.error("Cannot fetch Firebase public keys: %s", exc)
        raise AuthServiceUnavailable() from exc
    except fb_exceptions.FirebaseError as exc:
        logger.error("Firebase error while verifying token: %s", type(exc).__name__)
        raise AuthServiceUnavailable() from exc
    except ValueError as exc:
        raise InvalidToken() from exc


def ensure_verified_account(email):
    """Get or create the Firebase account for `email`, marked as verified.

    Used only by trusted provisioning (manage.py command / Admin UI) for
    project accounts without a real inbox. A new account gets a random
    password nobody knows; the owner sets their own via password_setup_link().
    Returns the Firebase UID.
    """
    app = _app()
    try:
        try:
            record = auth.get_user_by_email(email, app=app)
        except auth.UserNotFoundError:
            record = auth.create_user(
                email=email, email_verified=True, password=secrets.token_urlsafe(32), app=app
            )
            logger.info("Created Firebase account %s", email)
        else:
            if not record.email_verified:
                auth.update_user(record.uid, email_verified=True, app=app)
            if record.disabled:
                auth.update_user(record.uid, disabled=False, app=app)
        return record.uid
    except fb_exceptions.FirebaseError as exc:
        logger.error("Firebase error while provisioning %s: %s", email, type(exc).__name__)
        raise AuthServiceUnavailable() from exc


def password_setup_link(email):
    """One-time link (valid ~1 hour) that lets the account owner set a password."""
    try:
        return auth.generate_password_reset_link(email, app=_app())
    except fb_exceptions.FirebaseError as exc:
        logger.error("Firebase error while generating password link: %s", type(exc).__name__)
        raise AuthServiceUnavailable() from exc
