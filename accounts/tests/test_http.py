"""Middleware, session sign-in, logout, RBAC enforcement and commands."""

from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import ApprovedAdmin, Role
from accounts.services.account_service import role_of
from accounts.services.exceptions import AuthServiceUnavailable, InvalidToken

from .conftest import ADMIN_EMAIL, USER_EMAIL

pytestmark = pytest.mark.django_db
User = get_user_model()

ME_URL = reverse("api-me")
SESSION_URL = reverse("session-login")


def bearer(token="good-token"):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# --- Bearer middleware ----------------------------------------------------------------

def test_valid_bearer_token_authenticates(firebase_token):
    with firebase_token():
        response = APIClient().get(ME_URL, **bearer())
    assert response.status_code == 200
    assert response.data["email"] == USER_EMAIL
    assert response.data["role"] == "USER"
    assert response.data["agency"] == "dict"


def test_bearer_requests_do_not_need_csrf(firebase_token):
    client = APIClient(enforce_csrf_checks=True)
    with firebase_token():
        response = client.post(reverse("api:reservation-create"), {}, format="json", **bearer())
    assert response.status_code == 400  # reached validation, not a CSRF 403


@pytest.mark.parametrize(
    "error, status, code",
    [
        (InvalidToken(), 401, "invalid_token"),
        (AuthServiceUnavailable(), 503, "auth_unavailable"),
    ],
)
def test_bearer_failures(firebase_token, error, status, code):
    with firebase_token(error):
        response = APIClient().get(ME_URL, **bearer("bad"))
    assert response.status_code == status
    assert response.json()["code"] == code
    if status == 401:
        assert response["WWW-Authenticate"].startswith("Bearer")


def test_bearer_unverified_email_is_403(firebase_token):
    with firebase_token(verified=False):
        response = APIClient().get(ME_URL, **bearer())
    assert response.status_code == 403
    assert response.json()["code"] == "email_not_verified"


def test_bearer_unapproved_admin_is_403(firebase_token):
    with firebase_token(email=ADMIN_EMAIL):
        response = APIClient().get(ME_URL, **bearer())
    assert response.status_code == 403
    assert response.json()["code"] == "admin_not_approved"


def test_no_credentials_is_401_with_bearer_challenge():
    response = APIClient().get(ME_URL)
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_malformed_authorization_header_is_ignored_not_crashing():
    response = APIClient().get(ME_URL, HTTP_AUTHORIZATION="Basic abc")
    assert response.status_code == 401


# --- Session sign-in ---------------------------------------------------------------------

@pytest.fixture
def csrf_client():
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("login"))  # sets the csrftoken cookie
    return client


def post_session(client, token="good-token", next_url=None):
    data = {"idToken": token}
    if next_url:
        data["next"] = next_url
    return client.post(
        SESSION_URL, data, content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value
    )


def test_session_sign_in_starts_session(csrf_client, firebase_token):
    with firebase_token():
        response = post_session(csrf_client)
    assert response.status_code == 200
    assert response.json() == {"redirect": reverse("reservations:calendar"), "role": "USER"}
    assert csrf_client.get(reverse("reservations:calendar")).status_code == 200


def test_session_sign_in_requires_csrf(firebase_token):
    client = Client(enforce_csrf_checks=True)
    with firebase_token():
        response = client.post(SESSION_URL, {"idToken": "good"}, content_type="application/json")
    assert response.status_code == 403
    assert "_auth_user_id" not in client.session


def test_session_sign_in_rejects_stale_token(csrf_client, firebase_token):
    with firebase_token(auth_age=600):
        response = post_session(csrf_client)
    assert response.status_code == 401
    assert response.json()["code"] == "recent_sign_in_required"


def test_session_sign_in_requires_token(csrf_client):
    response = csrf_client.post(
        SESSION_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf_client.cookies["csrftoken"].value
    )
    assert response.status_code == 400


def test_session_sign_in_ignores_offsite_next(csrf_client, firebase_token):
    with firebase_token():
        response = post_session(csrf_client, next_url="https://evil.example/")
    assert response.json()["redirect"] == reverse("reservations:calendar")


def test_session_sign_in_is_throttled(csrf_client, firebase_token, monkeypatch):
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth_session": "2/min"})
    with firebase_token(InvalidToken()):
        statuses = [post_session(csrf_client).status_code for _ in range(3)]
    assert statuses == [401, 401, 429]


def test_login_page_renders_firebase_config(client, settings):
    settings.FIREBASE_WEB_CONFIG = {"apiKey": "k", "authDomain": "d", "projectId": "p", "appId": "a"}
    response = client.get(reverse("login"))
    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="firebase-config"' in content and '"projectId": "p"' in content
    assert "importmap" in content
    assert 'name="password"' not in content  # no Django password form any more


def test_logout(client, firebase_token):
    user = User.objects.create_user(username=USER_EMAIL, email=USER_EMAIL)
    client.force_login(user)
    assert client.get(reverse("logout")).status_code == 405
    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?signed_out=1"
    assert "_auth_user_id" not in client.session


# --- RBAC: Django admin is Admin-only ---------------------------------------------------

def make(email, role):
    user = User.objects.create_user(username=email, email=email)
    user.profile.role = role
    user.profile.save()
    if role == Role.ADMIN:
        ApprovedAdmin.objects.create(email=email)
        user.is_staff = user.is_superuser = True
        user.save()
    return user


def test_admin_site_anonymous_goes_to_firebase_login(client):
    response = client.get("/admin/", follow=True)
    assert response.redirect_chain[-1][0].startswith(reverse("login"))


@pytest.mark.parametrize("role, email", [(Role.USER, USER_EMAIL), (Role.SCHEDULER, "pedrosantos@dict.gov.ph")])
def test_admin_site_forbidden_for_non_admins(client, role, email):
    client.force_login(make(email, role))
    response = client.get("/admin/", follow=True)
    assert response.status_code == 403


def test_admin_site_allowed_for_admin(client):
    client.force_login(make(ADMIN_EMAIL, Role.ADMIN))
    assert client.get("/admin/").status_code == 200


def test_admin_approves_new_admin_in_admin_site(client):
    admin = make(ADMIN_EMAIL, Role.ADMIN)
    client.force_login(admin)
    with mock.patch("accounts.firebase.ensure_verified_account", return_value="uid-2"), mock.patch(
        "accounts.firebase.password_setup_link", return_value="https://example.test/link"
    ):
        response = client.post(
            reverse("admin:accounts_approvedadmin_add"), {"email": "govfleetadmin02@dost.gov.ph"}, follow=True
        )
    assert response.status_code == 200
    assert b"https://example.test/link" in response.content
    new = ApprovedAdmin.objects.get(email="govfleetadmin02@dost.gov.ph")
    assert new.approved_by == admin
    assert role_of(User.objects.get(email="govfleetadmin02@dost.gov.ph")) == Role.ADMIN


def test_admin_site_rejects_non_admin_pattern(client):
    client.force_login(make(ADMIN_EMAIL, Role.ADMIN))
    response = client.post(reverse("admin:accounts_approvedadmin_add"), {"email": "kcdimayuga@dict.gov.ph"})
    assert response.status_code == 200  # form re-rendered with an error
    assert not ApprovedAdmin.objects.filter(email="kcdimayuga@dict.gov.ph").exists()


def test_permission_classes():
    from accounts.permissions import IsAdminRole, IsStaffRole

    req = lambda u: mock.Mock(user=u)  # noqa: E731
    admin, sched, user = make(ADMIN_EMAIL, Role.ADMIN), make("pedrosantos@dict.gov.ph", Role.SCHEDULER), make(USER_EMAIL, Role.USER)
    assert IsAdminRole().has_permission(req(admin), None)
    assert not IsAdminRole().has_permission(req(sched), None)
    assert IsStaffRole().has_permission(req(sched), None)
    assert not IsStaffRole().has_permission(req(user), None)


# --- management commands ------------------------------------------------------------------

@pytest.fixture
def fake_provisioning():
    with mock.patch("accounts.firebase.ensure_verified_account", return_value="uid-cmd"), mock.patch(
        "accounts.firebase.password_setup_link", return_value="https://example.test/set-password"
    ):
        yield


def test_create_admin_command(fake_provisioning):
    out = StringIO()
    call_command("create_admin", ADMIN_EMAIL, stdout=out)
    assert "https://example.test/set-password" in out.getvalue()
    user = User.objects.get(email=ADMIN_EMAIL)
    assert role_of(user) == Role.ADMIN and user.is_staff
    assert ApprovedAdmin.objects.filter(email=ADMIN_EMAIL).exists()


def test_create_admin_command_rejects_wrong_format(fake_provisioning):
    with pytest.raises(CommandError):
        call_command("create_admin", "admin@dict.gov.ph", stdout=StringIO())


def test_create_user_command_scheduler(fake_provisioning):
    call_command("create_user", "pedrosantos@dict.gov.ph", "--scheduler", stdout=StringIO())
    assert role_of(User.objects.get(email="pedrosantos@dict.gov.ph")) == Role.SCHEDULER
