"""Local shadow records for Firebase users, carrying the RBAC role."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .services.email_policy import is_admin_email, normalize_email


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    SCHEDULER = "SCHEDULER", "Scheduler"
    USER = "USER", "User"


# Roles allowed to see everyone's reservations.
STAFF_ROLES = (Role.ADMIN, Role.SCHEDULER)


class Profile(models.Model):
    """One per Django user. Created automatically (see signals.py)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    firebase_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER, db_index=True)
    agency = models.CharField(max_length=63, blank=True, help_text="From the email domain, e.g. 'dict'.")
    display_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email or self.user.get_username()} ({self.get_role_display()})"

    def clean(self):
        email = self.user.email or ""
        if self.role == Role.ADMIN and not is_admin_email(email):
            raise ValidationError(
                {"role": "Only govfleetadminNN@<agency>.gov.ph accounts can be Admins."}
            )
        if self.role != Role.ADMIN and is_admin_email(email):
            raise ValidationError({"role": "govfleetadmin accounts must have the Admin role."})

    @property
    def is_staff_role(self):
        return self.role in STAFF_ROLES


class ApprovedAdmin(models.Model):
    """Admin emails approved in advance. Matching the email pattern alone is
    never enough to become Admin."""

    email = models.EmailField(unique=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Empty for the bootstrap admin created with `manage.py create_admin`.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "approved admin"

    def __str__(self):
        return self.email

    def clean(self):
        self.email = normalize_email(self.email)
        if not is_admin_email(self.email):
            raise ValidationError(
                {"email": "Must be in the form govfleetadminNN@<agency>.gov.ph."}
            )
