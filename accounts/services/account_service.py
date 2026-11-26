"""Business rules for Firebase sign-in and RBAC.

- A verified Firebase identity is mapped to a local shadow User + Profile.
- Email must follow the agency formats (email_policy).
- Admin = admin-pattern email + verified + pre-approved (ApprovedAdmin).
- Scheduler = a User promoted by an Admin (role kept across sign-ins).
"""

import logging
import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from .. import firebase
from ..models import ApprovedAdmin, Profile, Role
from .email_policy import agency_of, is_admin_email, is_user_email, normalize_email
from .exceptions import (
    AccountDisabled,
    AdminNotApproved,
    EmailNotAllowed,
    EmailNotVerified,
    InvalidToken,
    StaleSignIn,
)

logger = logging.getLogger("govfleet.auth")


class AccountService:
    # A session may only be started from a sign-in at most this old
    # (Firebase's recommendation for session creation).
    MAX_SIGN_IN_AGE_SECONDS = 5 * 60

    # --- Sign-in -------------------------------------------------------------

    @classmethod
    def authenticate_token(cls, id_token, *, require_recent_sign_in=False):
        """Verify a Firebase ID token and return the local Django user."""
        claims = firebase.verify_id_token(id_token)
        if require_recent_sign_in:
            auth_time = claims.get("auth_time")
            if not isinstance(auth_time, (int, float)) or time.time() - auth_time > cls.MAX_SIGN_IN_AGE_SECONDS:
                raise StaleSignIn()
        return cls.sync_user(claims)

    @classmethod
    def sync_user(cls, claims):
        """Map verified Firebase claims to a local user, enforcing the RBAC rules."""
        uid = claims.get("uid") or claims.get("sub")
        email = normalize_email(claims.get("email"))
        if not uid:
            raise InvalidToken()
        if not email:
            raise EmailNotAllowed()
        if not claims.get("email_verified"):
            raise EmailNotVerified()

        if is_admin_email(email):
            if not ApprovedAdmin.objects.filter(email=email).exists():
                logger.warning("Sign-in refused: admin email %s is not approved", email)
                raise AdminNotApproved()
            role = Role.ADMIN
        elif is_user_email(email):
            role = None  # keep an existing USER/SCHEDULER role
        else:
            raise EmailNotAllowed()

        try:
            user = cls._upsert_local(uid, email, role, display_name=claims.get("name", ""))
        except IntegrityError:
            # Two first sign-ins raced; the other one created the row.
            user = cls._upsert_local(uid, email, role, display_name=claims.get("name", ""))

        if not user.is_active:
            raise AccountDisabled()
        return user

    # --- Provisioning (trusted callers only) ---------------------------------

    @classmethod
    def provision_admin(cls, email, *, approved_by=None):
        """Approve an admin email, create its verified Firebase account and local user.

        Returns (user, password_setup_link).
        """
        email = normalize_email(email)
        if not is_admin_email(email):
            raise EmailNotAllowed("Admin emails must be in the form govfleetadminNN@agency.gov.ph.")
        uid = firebase.ensure_verified_account(email)  # network call: outside the transaction
        with transaction.atomic():
            ApprovedAdmin.objects.get_or_create(email=email, defaults={"approved_by": approved_by})
            user = cls._upsert_local(uid, email, Role.ADMIN)
            if not user.is_active:  # re-approval of a previously revoked admin
                user.is_active = True
                user.save(update_fields=["is_active"])
        logger.info("Provisioned admin %s (approved by %s)", email, approved_by or "bootstrap command")
        return user, firebase.password_setup_link(email)

    @classmethod
    def provision_user(cls, email, *, role=Role.USER):
        """Create a verified User/Scheduler account (for project accounts without an inbox)."""
        email = normalize_email(email)
        if not is_user_email(email):
            raise EmailNotAllowed()
        if role not in (Role.USER, Role.SCHEDULER):
            raise ValueError("Use provision_admin for Admin accounts.")
        uid = firebase.ensure_verified_account(email)
        with transaction.atomic():
            user = cls._upsert_local(uid, email, role)
        return user, firebase.password_setup_link(email)

    @staticmethod
    def revoke_admin(email):
        """Remove an admin approval and deactivate the account (ends its sessions)."""
        email = normalize_email(email)
        User = get_user_model()
        with transaction.atomic():
            ApprovedAdmin.objects.filter(email=email).delete()
            User.objects.filter(username=email).update(is_active=False)
        logger.info("Revoked admin %s", email)

    @staticmethod
    def sync_role_flags(user):
        """Keep Django's is_staff/is_superuser in line with the RBAC role
        (only Admins may use the Django admin)."""
        is_admin = role_of(user) == Role.ADMIN
        if user.is_staff != is_admin or user.is_superuser != is_admin:
            user.is_staff = user.is_superuser = is_admin
            user.save(update_fields=["is_staff", "is_superuser"])

    # --- Internals -----------------------------------------------------------

    @staticmethod
    def _upsert_local(uid, email, role, display_name=""):
        """Create or update the shadow User + Profile. `role=None` keeps the current role."""
        User = get_user_model()
        with transaction.atomic():
            profile = (
                Profile.objects.select_for_update().select_related("user").filter(firebase_uid=uid).first()
            )
            if profile is None:
                # First sign-in with this UID: match a pre-provisioned account by
                # email (the email is verified, so it is the same person).
                user, _ = User.objects.get_or_create(username=email, defaults={"email": email})
                profile, _ = Profile.objects.select_for_update().get_or_create(user=user)
                profile.firebase_uid = uid
            user = profile.user

            new_role = role or (profile.role if profile.role != Role.ADMIN else Role.USER)
            profile.role = new_role
            profile.agency = agency_of(email)
            if display_name:
                profile.display_name = display_name[:150]
            profile.save()

            is_admin = new_role == Role.ADMIN
            changed = False
            for field, value in (
                ("username", email),
                ("email", email),
                ("is_staff", is_admin),
                ("is_superuser", is_admin),
            ):
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed = True
            if user.has_usable_password():
                user.set_unusable_password()  # Firebase is the only credential store.
                changed = True
            if changed:
                user.save()
            return user


def role_of(user):
    """RBAC role of a Django user (None if anonymous)."""
    if user is None or not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return profile.role if profile is not None else Role.USER


def is_staff_role(user):
    return role_of(user) in (Role.ADMIN, Role.SCHEDULER)
