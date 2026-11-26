"""manage.py create_admin govfleetadmin01@dict.gov.ph

Bootstrap (or re-approve) an Admin: approves the email, creates the Firebase
account already marked verified (project accounts have no inbox), creates
the local Admin user, and prints a one-time link to set the password.
Only someone with server access can run this.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.services.account_service import AccountService
from accounts.services.exceptions import AccountError


class Command(BaseCommand):
    help = "Approve and create an Admin account (govfleetadminNN@agency.gov.ph)."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email, **options):
        try:
            user, link = AccountService.provision_admin(email)
        except AccountError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(self.style.SUCCESS(f"Admin ready: {user.email}"))
        self.stdout.write(
            "Open this one-time link to set the password (expires in about 1 hour, single use):"
        )
        self.stdout.write(link)
