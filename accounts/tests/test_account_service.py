from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import ApprovedAdmin, Profile, Role
from accounts.services.account_service import AccountService, role_of
from accounts.services.exceptions import (
    AccountDisabled,
    AdminNotApproved,
    EmailNotAllowed,
    EmailNotVerified,
    InvalidToken,
    StaleSignIn,
)

from .conftest import ADMIN_EMAIL, USER_EMAIL

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_first_sign_in_creates_user_with_user_role(claims):
    user = AccountService.sync_user(claims())
    assert user.email == user.username == USER_EMAIL
    assert role_of(user) == Role.USER
    assert user.profile.agency == "dict"
    assert user.profile.firebase_uid == "uid-juandelacruz"
    assert user.profile.display_name == "Juan Dela Cruz"
    assert not user.is_staff and not user.is_superuser
    assert not user.has_usable_password()


def test_second_sign_in_reuses_the_same_user(claims):
    first = AccountService.sync_user(claims())
    second = AccountService.sync_user(claims())
    assert first.pk == second.pk
    assert User.objects.count() == 1


def test_unverified_email_is_refused(claims):
    with pytest.raises(EmailNotVerified):
        AccountService.sync_user(claims(verified=False))
    assert not User.objects.exists()


@pytest.mark.parametrize("email", ["juan@gmail.com", "juan.delacruz@dict.gov.ph", "juan2@dict.gov.ph"])
def test_wrong_email_format_is_refused(claims, email):
    with pytest.raises(EmailNotAllowed):
        AccountService.sync_user(claims(email=email))


def test_missing_uid_or_email(claims):
    with pytest.raises(InvalidToken):
        AccountService.sync_user(claims(uid="", sub=""))
    with pytest.raises(EmailNotAllowed):
        AccountService.sync_user(claims(email=""))


def test_admin_pattern_alone_is_not_enough(claims):
    with pytest.raises(AdminNotApproved):
        AccountService.sync_user(claims(email=ADMIN_EMAIL))
    assert not User.objects.exists()


def test_approved_verified_admin_gets_admin_role(claims, approved_admin):
    user = AccountService.sync_user(claims(email=ADMIN_EMAIL))
    assert role_of(user) == Role.ADMIN
    assert user.is_staff and user.is_superuser


def test_unverified_approved_admin_is_refused(claims, approved_admin):
    with pytest.raises(EmailNotVerified):
        AccountService.sync_user(claims(email=ADMIN_EMAIL, verified=False))


def test_scheduler_role_survives_sign_in(claims):
    user = AccountService.sync_user(claims())
    user.profile.role = Role.SCHEDULER
    user.profile.save()
    again = AccountService.sync_user(claims())
    assert role_of(again) == Role.SCHEDULER
    assert not again.is_staff  # only Admins use the Django admin


def test_preprovisioned_account_is_bound_on_first_sign_in(claims):
    pre = User.objects.create_user(username=USER_EMAIL, email=USER_EMAIL)
    user = AccountService.sync_user(claims(uid="real-firebase-uid"))
    assert user.pk == pre.pk
    assert user.profile.firebase_uid == "real-firebase-uid"


def test_disabled_account_is_refused(claims):
    user = AccountService.sync_user(claims())
    user.is_active = False
    user.save()
    with pytest.raises(AccountDisabled):
        AccountService.sync_user(claims())


def test_session_requires_recent_sign_in(claims):
    with mock.patch("accounts.firebase.verify_id_token", return_value=claims(auth_age=600)):
        with pytest.raises(StaleSignIn):
            AccountService.authenticate_token("token", require_recent_sign_in=True)
        # Fine for per-request Bearer auth (token itself is still valid).
        assert AccountService.authenticate_token("token").email == USER_EMAIL


# --- provisioning --------------------------------------------------------------------

@pytest.fixture
def fake_provisioning():
    with mock.patch("accounts.firebase.ensure_verified_account", return_value="fb-uid-1") as ensure, mock.patch(
        "accounts.firebase.password_setup_link", return_value="https://example.test/set-password"
    ) as link:
        yield ensure, link


def test_provision_admin(fake_provisioning):
    user, link = AccountService.provision_admin(" GovFleetAdmin01@DICT.gov.ph ")
    assert link == "https://example.test/set-password"
    assert user.email == ADMIN_EMAIL
    assert role_of(user) == Role.ADMIN and user.is_staff
    assert ApprovedAdmin.objects.filter(email=ADMIN_EMAIL, approved_by=None).exists()
    fake_provisioning[0].assert_called_once_with(ADMIN_EMAIL)


def test_provision_admin_rejects_non_admin_email(fake_provisioning):
    with pytest.raises(EmailNotAllowed):
        AccountService.provision_admin("kcdimayuga@dict.gov.ph")
    fake_provisioning[0].assert_not_called()


def test_revoke_and_reapprove_admin(fake_provisioning):
    user, _ = AccountService.provision_admin(ADMIN_EMAIL)
    AccountService.revoke_admin(ADMIN_EMAIL)
    user.refresh_from_db()
    assert not user.is_active
    assert not ApprovedAdmin.objects.exists()

    user, _ = AccountService.provision_admin(ADMIN_EMAIL)
    assert user.is_active


def test_provision_user_and_scheduler(fake_provisioning):
    user, _ = AccountService.provision_user("kcdimayuga@dict.gov.ph")
    assert role_of(user) == Role.USER
    sched, _ = AccountService.provision_user("pedrosantos@dost.gov.ph", role=Role.SCHEDULER)
    assert role_of(sched) == Role.SCHEDULER
    with pytest.raises(EmailNotAllowed):
        AccountService.provision_user(ADMIN_EMAIL)


# --- model validation ------------------------------------------------------------------

def test_profile_role_must_match_email_kind():
    user = User.objects.create_user(username=USER_EMAIL, email=USER_EMAIL)
    user.profile.role = Role.ADMIN
    with pytest.raises(ValidationError):
        user.profile.full_clean()

    admin = User.objects.create_user(username=ADMIN_EMAIL, email=ADMIN_EMAIL)
    admin.profile.role = Role.SCHEDULER
    with pytest.raises(ValidationError):
        admin.profile.full_clean()


def test_approved_admin_requires_admin_pattern():
    with pytest.raises(ValidationError):
        ApprovedAdmin(email="kcdimayuga@dict.gov.ph").full_clean()
    ApprovedAdmin(email=ADMIN_EMAIL).full_clean()


def test_profile_is_created_automatically():
    user = User.objects.create_user(username="x@dict.gov.ph")
    assert Profile.objects.filter(user=user, role=Role.USER).exists()
