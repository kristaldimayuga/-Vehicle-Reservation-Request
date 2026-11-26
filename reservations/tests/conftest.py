from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from reservations.models import Vehicle


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache; don't let them leak between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    email = "juandelacruz@dict.gov.ph"
    return get_user_model().objects.create_user(username=email, email=email)


@pytest.fixture
def other_user(db):
    email = "mariaclara@dost.gov.ph"
    return get_user_model().objects.create_user(username=email, email=email)


@pytest.fixture
def make_account(db):
    """Create a local user with a given RBAC role (no Firebase involved)."""
    from accounts.models import ApprovedAdmin, Role

    def make(email, role=Role.USER):
        u = get_user_model().objects.create_user(username=email, email=email)
        u.profile.role = role
        u.profile.save()
        if role == Role.ADMIN:
            ApprovedAdmin.objects.get_or_create(email=email)
            u.is_staff = u.is_superuser = True
            u.save()
        return u

    return make


@pytest.fixture
def admin_user(make_account):
    from accounts.models import Role

    return make_account("govfleetadmin01@dict.gov.ph", Role.ADMIN)


@pytest.fixture
def scheduler_user(make_account):
    from accounts.models import Role

    return make_account("pedrosantos@dict.gov.ph", Role.SCHEDULER)


@pytest.fixture
def vehicle(db):
    return Vehicle.objects.create(plate_number="SAB-1234", name="Toyota Hiace", capacity=12)


@pytest.fixture
def slot():
    """A future [start, end) window rounded to the hour."""
    start = (timezone.now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=3)


@pytest.fixture
def client_for():
    def make(u):
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    return make


@pytest.fixture
def api_client(client_for, user):
    return client_for(user)
