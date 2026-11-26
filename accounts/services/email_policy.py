"""Allowed email formats.

- Admin: govfleetadminNN@<agency>.gov.ph   e.g. govfleetadmin01@dict.gov.ph
- User:  firstnamelastname@<agency>.gov.ph e.g. kcdimayuga@dict.gov.ph

Matching the Admin pattern does NOT make someone an Admin by itself; the
address must also be verified and pre-approved (see account_service).
"""

import re

ADMIN_EMAIL_RE = re.compile(r"^govfleetadmin\d{2}@(?P<agency>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\.gov\.ph$")
USER_EMAIL_RE = re.compile(r"^(?P<local>[a-z]{2,64})@(?P<agency>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\.gov\.ph$")
RESERVED_PREFIX = "govfleetadmin"


def normalize_email(email):
    return (email or "").strip().lower()


def is_admin_email(email):
    return bool(ADMIN_EMAIL_RE.match(normalize_email(email)))


def is_user_email(email):
    match = USER_EMAIL_RE.match(normalize_email(email))
    return bool(match) and not match.group("local").startswith(RESERVED_PREFIX)


def agency_of(email):
    email = normalize_email(email)
    match = ADMIN_EMAIL_RE.match(email) or USER_EMAIL_RE.match(email)
    return match.group("agency") if match else ""
