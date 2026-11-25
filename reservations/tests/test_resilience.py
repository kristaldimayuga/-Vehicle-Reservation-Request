"""Behaviour when the database is unreachable (LA3 TC-05) and /health/.

A real outage can't be produced inside the test database, so the failing
layer is patched to raise the same exception psycopg2 raises when
PostgreSQL is down (django.db.OperationalError).
"""

import logging
from unittest import mock

import pytest
from django.conf import settings
from django.db import OperationalError
from django.test import Client
from django.urls import reverse

from govfleet import health

CREATE_URL = reverse("api:reservation-create")
DB_DOWN = OperationalError('connection to server at "127.0.0.1", port 5432 failed: Connection refused')


def payload(vehicle, start, end):
    return {
        "vehicle": vehicle.pk,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "purpose": "Site visit",
    }


# --- API: DRF exception handler -------------------------------------------------

@pytest.mark.django_db
def test_api_db_outage_returns_503_json(api_client, vehicle, slot):
    with mock.patch(
        "reservations.api.views.VehicleReservationService.create_reservation", side_effect=DB_DOWN
    ):
        response = api_client.post(CREATE_URL, payload(vehicle, *slot), format="json")

    assert response.status_code == 503
    assert response["Content-Type"] == "application/json"
    assert response["Retry-After"] == "30"
    assert response.json()["code"] == "service_unavailable"
    # No internals leaked to the client.
    body = response.content.decode()
    assert "5432" not in body and "Traceback" not in body and "refused" not in body


@pytest.mark.django_db
def test_api_db_outage_is_logged(api_client, vehicle, slot, caplog):
    # The "govfleet" logger doesn't propagate to root, so attach caplog to it.
    govfleet_logger = logging.getLogger("govfleet")
    govfleet_logger.addHandler(caplog.handler)
    try:
        with mock.patch(
            "reservations.api.views.VehicleReservationService.create_reservation", side_effect=DB_DOWN
        ):
            api_client.post(CREATE_URL, payload(vehicle, *slot), format="json")
    finally:
        govfleet_logger.removeHandler(caplog.handler)

    records = [r for r in caplog.records if r.name == "govfleet.api"]
    assert records and records[0].levelname == "ERROR"
    assert "ReservationCreateView" in records[0].getMessage()


@pytest.mark.django_db
def test_api_unexpected_error_returns_generic_500_json(api_client, vehicle, slot):
    with mock.patch(
        "reservations.api.views.VehicleReservationService.create_reservation",
        side_effect=RuntimeError("secret internal detail"),
    ):
        response = api_client.post(CREATE_URL, payload(vehicle, *slot), format="json")

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred.", "code": "server_error"}
    assert "secret" not in response.content.decode()


@pytest.mark.django_db
def test_api_db_outage_on_read_endpoint_returns_503(api_client):
    with mock.patch("reservations.api.views.VehicleReservationService.calendar_reservations", side_effect=DB_DOWN):
        response = api_client.get(
            reverse("api:calendar-events"),
            {"start": "2026-12-01T00:00:00+08:00", "end": "2026-12-08T00:00:00+08:00"},
        )
    assert response.status_code == 503


# --- HTML pages: middleware ------------------------------------------------------

@pytest.mark.django_db
def test_page_db_outage_returns_friendly_503_page(client, user):
    client.force_login(user)
    with mock.patch("reservations.views.render", side_effect=DB_DOWN):
        response = client.get(reverse("reservations:calendar"))

    assert response.status_code == 503
    assert response["Retry-After"] == "30"
    assert b"temporarily unavailable" in response.content
    assert b"Traceback" not in response.content and b"5432" not in response.content


@pytest.mark.django_db
def test_middleware_ignores_non_database_errors(user):
    client = Client(raise_request_exception=True)
    client.force_login(user)
    with mock.patch("reservations.views.render", side_effect=ValueError("bug")):
        with pytest.raises(ValueError):
            client.get(reverse("reservations:calendar"))


# --- /health/ ----------------------------------------------------------------------

@pytest.mark.django_db
def test_health_ok_without_login(client):
    response = client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert "no-cache" in response["Cache-Control"]


def test_health_reports_503_when_database_unreachable(client):
    with mock.patch.object(health, "database_is_reachable", return_value=False):
        response = client.get(reverse("health"))
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}


def test_database_is_reachable_handles_connection_error():
    fake_connection = mock.Mock()
    fake_connection.cursor.side_effect = DB_DOWN
    with mock.patch.object(health, "connection", fake_connection):
        assert health.database_is_reachable() is False


def test_health_rejects_post(client):
    assert client.post(reverse("health")).status_code == 405


# --- connection settings (A2) ----------------------------------------------------

def test_database_fails_fast():
    db = settings.DATABASES["default"]
    assert 0 < db["OPTIONS"]["connect_timeout"] <= 10
    assert db["CONN_HEALTH_CHECKS"] is True
