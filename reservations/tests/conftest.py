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
    return get_user_model().objects.create_user(username="juan", password="s3cure-pass-123")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="maria", password="s3cure-pass-456")


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
