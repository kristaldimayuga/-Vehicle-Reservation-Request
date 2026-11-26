"""accounts.firebase translates firebase-admin errors into domain errors."""

from unittest import mock

import pytest
from firebase_admin import auth

from accounts import firebase
from accounts.services.exceptions import AuthServiceUnavailable, InvalidToken


@pytest.fixture
def fake_app():
    with mock.patch.object(firebase, "_app", return_value=object()) as app:
        yield app


@pytest.mark.parametrize(
    "error",
    [
        auth.InvalidIdTokenError("bad signature"),
        auth.ExpiredIdTokenError("expired", None),
        auth.RevokedIdTokenError("revoked"),
        auth.UserDisabledError("disabled"),
    ],
)
def test_bad_tokens_become_invalid_token(fake_app, error):
    with mock.patch.object(auth, "verify_id_token", side_effect=error):
        with pytest.raises(InvalidToken):
            firebase.verify_id_token("some.jwt.token")


def test_certificate_fetch_failure_is_503(fake_app):
    with mock.patch.object(auth, "verify_id_token", side_effect=auth.CertificateFetchError("down", None)):
        with pytest.raises(AuthServiceUnavailable):
            firebase.verify_id_token("some.jwt.token")


def test_verify_checks_revocation(fake_app):
    with mock.patch.object(auth, "verify_id_token", return_value={"uid": "u"}) as verify:
        assert firebase.verify_id_token("some.jwt.token") == {"uid": "u"}
    assert verify.call_args.kwargs["check_revoked"] is True


@pytest.mark.parametrize("token", ["", None, 123])
def test_empty_token_rejected_without_calling_firebase(fake_app, token):
    with mock.patch.object(auth, "verify_id_token") as verify:
        with pytest.raises(InvalidToken):
            firebase.verify_id_token(token)
    verify.assert_not_called()


def test_missing_credentials_is_503(settings):
    settings.FIREBASE_CREDENTIALS = ""
    with mock.patch("firebase_admin.get_app", side_effect=ValueError):
        with pytest.raises(AuthServiceUnavailable):
            firebase._app()


def test_unreadable_credentials_is_503(settings, tmp_path):
    settings.FIREBASE_CREDENTIALS = str(tmp_path / "missing.json")
    with mock.patch("firebase_admin.get_app", side_effect=ValueError):
        with pytest.raises(AuthServiceUnavailable):
            firebase._app()


def test_ensure_verified_account_creates_missing_account(fake_app):
    created = mock.Mock(uid="new-uid")
    with mock.patch.object(auth, "get_user_by_email", side_effect=auth.UserNotFoundError("none")), mock.patch.object(
        auth, "create_user", return_value=created
    ) as create:
        assert firebase.ensure_verified_account("govfleetadmin01@dict.gov.ph") == "new-uid"
    kwargs = create.call_args.kwargs
    assert kwargs["email_verified"] is True
    assert len(kwargs["password"]) >= 32  # random, never shown


def test_ensure_verified_account_verifies_existing_account(fake_app):
    existing = mock.Mock(uid="old-uid", email_verified=False, disabled=False)
    with mock.patch.object(auth, "get_user_by_email", return_value=existing), mock.patch.object(
        auth, "update_user"
    ) as update:
        assert firebase.ensure_verified_account("govfleetadmin01@dict.gov.ph") == "old-uid"
    update.assert_called_once_with("old-uid", email_verified=True, app=fake_app.return_value)
