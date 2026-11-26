"""manage.py create_user kcdimayuga@dict.gov.ph [--scheduler]

Create a verified User (or Scheduler) account for project/demo addresses
that have no real inbox, and print a one-time link to set the password.
Real users can instead sign up on the login page and verify their email.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role
from accounts.services.account_service import AccountService
from accounts.services.exceptions import AccountError


class Command(BaseCommand):
    help = "Create a verified User account (firstnamelastname@agency.gov.ph)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--scheduler", action="store_true", help="Give the account the Scheduler role.")

    def handle(self, *args, email, scheduler, **options):
        role = Role.SCHEDULER if scheduler else Role.USER
        try:
            user, link = AccountService.provision_user(email, role=role)
        except AccountError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(self.style.SUCCESS(f"{role.label} ready: {user.email}"))
        self.stdout.write(
            "Open this one-time link to set the password (expires in about 1 hour, single use):"
        )
        self.stdout.write(link)
