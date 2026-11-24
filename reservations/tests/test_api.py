from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from reservations.models import Reservation

pytestmark = pytest.mark.django_db

CREATE_URL = reverse("api:reservation-create")
EVENTS_URL = reverse("api:calendar-events")


def payload(vehicle, start, end, purpose="Site visit"):
    return {
        "vehicle": vehicle.pk,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "purpose": purpose,
    }


# --- authentication -----------------------------------------------------------

@pytest.mark.parametrize(
    "method, url",
    [
        ("post", CREATE_URL),
        ("get", reverse("api:vehicle-list")),
        ("get", EVENTS_URL),
    ],
)
def test_unauthenticated_returns_401(method, url):
    response = getattr(APIClient(), method)(url)
    assert response.status_code == 401


# --- create -------------------------------------------------------------------

def test_create_returns_201_pending(api_client, user, vehicle, slot):
    response = api_client.post(CREATE_URL, payload(vehicle, *slot), format="json")
    assert response.status_code == 201
    assert response.data["status"] == "PENDING"
    assert response.data["vehicle"]["plate_number"] == vehicle.plate_number
    assert Reservation.objects.get().requester == user


def test_overlap_returns_409_without_leaking_details(api_client, client_for, other_user, vehicle, slot):
    api_client.post(CREATE_URL, payload(vehicle, *slot, purpose="Confidential"), format="json")
    start, end = slot
    response = client_for(other_user).post(
        CREATE_URL, payload(vehicle, start + timedelta(hours=1), end + timedelta(hours=1)), format="json"
    )
    assert response.status_code == 409
    assert response.data["code"] == "vehicle_unavailable"
    assert len(response.data["conflicts"]) == 1
    assert "purpose" not in response.data["conflicts"][0]
    assert "requester" not in response.data["conflicts"][0]


@pytest.mark.parametrize("missing", ["vehicle", "start_time", "end_time", "purpose"])
def test_missing_field_returns_400(api_client, vehicle, slot, missing):
    data = payload(vehicle, *slot)
    del data[missing]
    response = api_client.post(CREATE_URL, data, format="json")
    assert response.status_code == 400
    assert missing in response.data


def test_end_before_start_returns_400(api_client, vehicle, slot):
    start, end = slot
    response = api_client.post(CREATE_URL, payload(vehicle, end, start), format="json")
    assert response.status_code == 400
    assert "end_time" in response.data


def test_unknown_vehicle_returns_400(api_client, vehicle, slot):
    data = payload(vehicle, *slot)
    data["vehicle"] = 999999
    response = api_client.post(CREATE_URL, data, format="json")
    assert response.status_code == 400
    assert "vehicle" in response.data


def test_malformed_timestamp_returns_400(api_client, vehicle, slot):
    data = payload(vehicle, *slot)
    data["start_time"] = "not-a-date"
    response = api_client.post(CREATE_URL, data, format="json")
    assert response.status_code == 400


def test_inactive_vehicle_returns_400(api_client, vehicle, slot):
    vehicle.is_active = False
    vehicle.save()
    response = api_client.post(CREATE_URL, payload(vehicle, *slot), format="json")
    assert response.status_code == 400


# --- availability ---------------------------------------------------------------

def test_availability_endpoint(api_client, vehicle, slot):
    url = reverse("api:vehicle-availability", args=[vehicle.pk])
    params = {"start_time": slot[0].isoformat(), "end_time": slot[1].isoformat()}

    response = api_client.get(url, params)
    assert response.status_code == 200 and response.data["available"] is True

    api_client.post(CREATE_URL, payload(vehicle, *slot), format="json")
    response = api_client.get(url, params)
    assert response.status_code == 200 and response.data["available"] is False


def test_availability_unknown_vehicle_returns_404(api_client, slot):
    url = reverse("api:vehicle-availability", args=[999999])
    response = api_client.get(url, {"start_time": slot[0].isoformat(), "end_time": slot[1].isoformat()})
    assert response.status_code == 404


# --- vehicles & calendar -------------------------------------------------------

def test_vehicle_list_excludes_inactive(api_client, vehicle):
    from reservations.models import Vehicle

    Vehicle.objects.create(plate_number="OLD-0001", name="Retired van", is_active=False)
    response = api_client.get(reverse("api:vehicle-list"))
    assert [v["plate_number"] for v in response.data] == [vehicle.plate_number]


def test_calendar_events_hide_other_users_purpose(api_client, client_for, other_user, vehicle, slot):
    client_for(other_user).post(CREATE_URL, payload(vehicle, *slot, purpose="Secret trip"), format="json")
    params = {
        "start": (slot[0] - timedelta(days=1)).isoformat(),
        "end": (slot[1] + timedelta(days=1)).isoformat(),
    }
    response = api_client.get(EVENTS_URL, params)
    assert response.status_code == 200
    assert len(response.data) == 1
    event = response.data[0]
    assert event["extendedProps"]["isOwn"] is False
    assert "purpose" not in event["extendedProps"]
    assert "Secret" not in event["title"]


def test_calendar_events_show_own_purpose(api_client, vehicle, slot):
    api_client.post(CREATE_URL, payload(vehicle, *slot, purpose="My trip"), format="json")
    params = {"start": (slot[0] - timedelta(days=1)).isoformat(), "end": (slot[1] + timedelta(days=1)).isoformat()}
    event = api_client.get(EVENTS_URL, params).data[0]
    assert event["extendedProps"]["purpose"] == "My trip"


def test_calendar_events_requires_range(api_client):
    assert api_client.get(EVENTS_URL).status_code == 400


# --- page -----------------------------------------------------------------------

def test_calendar_page_requires_login(client):
    response = client.get(reverse("reservations:calendar"))
    assert response.status_code == 302
    assert reverse("login") in response["Location"]


def test_calendar_page_renders_for_logged_in_user(client, user):
    client.force_login(user)
    response = client.get(reverse("reservations:calendar"))
    assert response.status_code == 200
    assert b"fullcalendar" in response.content
