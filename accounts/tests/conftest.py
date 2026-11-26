import time
from unittest import mock

import pytest
from django.core.cache import cache

from accounts.models import ApprovedAdmin

ADMIN_EMAIL = "govfleetadmin01@dict.gov.ph"
USER_EMAIL = "juandelacruz@dict.gov.ph"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def claims():
    """Build decoded Firebase ID-token claims."""

    def make(email=USER_EMAIL, uid=None, verified=True, auth_age=0, **extra):
        data = {
            "uid": f"uid-{email.split('@')[0]}" if uid is None else uid,
            "email": email,
            "email_verified": verified,
            "auth_time": int(time.time()) - auth_age,
            "name": "Juan Dela Cruz",
        }
        data.update(extra)
        return data

    return make


@pytest.fixture
def firebase_token(claims):
    """Patch token verification: token string "good:<email>" -> verified claims
    for that email; anything else -> the side effect passed in."""

    def install(result=None, **claim_kwargs):
        def verify(token):
            if isinstance(result, Exception):
                raise result
            return result if isinstance(result, dict) else claims(**claim_kwargs)

        return mock.patch("accounts.firebase.verify_id_token", side_effect=verify)

    return install


@pytest.fixture
def approved_admin(db):
    return ApprovedAdmin.objects.create(email=ADMIN_EMAIL)
