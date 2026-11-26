"""Daily free-vehicle counts: users see how many vehicles are free per day,
never who booked them or when."""

from datetime import datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from reservations.models import Reservation, Vehicle
from reservations.services import ReservationValidationError, VehicleReservationService

pytestmark = pytest.mark.django_db

DAILY_URL = reverse("api:daily-availability")
DAY_URL = reverse("api:day-availability")


@pytest.fixture
def day():
    return timezone.localdate() + timedelta(days=5)


@pytest.fixture
def fleet(db):
    return [
        Vehicle.objects.create(plate_number=f"SAB-{n}000", name=f"Van {n}", capacity=10) for n in range(1, 4)
    ]


def at(d, hour, minute=0):
    return timezone.make_aware(datetime.combine(d, time(hour, minute)))


def book(user, vehicle, start, end, status=Reservation.Status.PENDING, purpose="Trip"):
    return Reservation.objects.create(
        requester=user, vehicle=vehicle, start_time=start, end_time=end, purpose=purpose, status=status
    )


def counts(first, last):
    return {d.day: d.available for d in VehicleReservationService.daily_availability(first, last)}


# --- service ------------------------------------------------------------------------

def test_all_free_when_nothing_booked(fleet, day):
    (result,) = VehicleReservationService.daily_availability(day, day)
    assert (result.total, result.available) == (3, 3)


def test_any_booking_that_day_takes_the_vehicle(user, fleet, day):
    book(user, fleet[0], at(day, 8), at(day, 10))
    assert counts(day - timedelta(days=1), day + timedelta(days=1)) == {
        day - timedelta(days=1): 3,
        day: 2,
        day + timedelta(days=1): 3,
    }


def test_two_bookings_of_same_vehicle_count_once(user, fleet, day):
    book(user, fleet[0], at(day, 8), at(day, 10))
    book(user, fleet[0], at(day, 13), at(day, 15))
    assert counts(day, day)[day] == 2


def test_booking_ending_at_midnight_does_not_take_next_day(user, fleet, day):
    book(user, fleet[0], at(day, 20), at(day + timedelta(days=1), 0))
    assert counts(day, day + timedelta(days=1)) == {day: 2, day + timedelta(days=1): 3}


def test_multi_day_booking_takes_every_day_it_touches(user, fleet, day):
    book(user, fleet[1], at(day, 20), at(day + timedelta(days=2), 2))
    assert counts(day, day + timedelta(days=3)) == {
        day: 2,
        day + timedelta(days=1): 2,
        day + timedelta(days=2): 2,
        day + timedelta(days=3): 3,
    }


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED", "COMPLETED"])
def test_non_blocking_statuses_free_the_vehicle(user, fleet, day, status):
    book(user, fleet[0], at(day, 8), at(day, 10), status=status)
    assert counts(day, day)[day] == 3


def test_inactive_vehicles_are_not_counted(user, fleet, day):
    fleet[2].is_active = False
    fleet[2].save()
    (result,) = VehicleReservationService.daily_availability(day, day)
    assert (result.total, result.available) == (2, 2)


def test_range_is_limited(fleet, day):
    with pytest.raises(ReservationValidationError):
        VehicleReservationService.daily_availability(day, day + timedelta(days=62))
    with pytest.raises(ReservationValidationError):
        VehicleReservationService.daily_availability(day, day - timedelta(days=1))


# --- API ------------------------------------------------------------------------------

def test_daily_endpoint_requires_login(day):
    response = APIClient().get(DAILY_URL, {"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()})
    assert response.status_code == 401


def test_daily_endpoint_returns_counts_only(api_client, other_user, fleet, day):
    book(other_user, fleet[0], at(day, 8), at(day, 10), purpose="Secret trip")
    response = api_client.get(DAILY_URL, {"start": day.isoformat(), "end": (day + timedelta(days=2)).isoformat()})
    assert response.status_code == 200
    assert response.data == [
        {"date": day.isoformat(), "total": 3, "available": 2},
        {"date": (day + timedelta(days=1)).isoformat(), "total": 3, "available": 3},
    ]


def test_daily_endpoint_rejects_bad_ranges(api_client, day):
    too_long = {"start": day.isoformat(), "end": (day + timedelta(days=63)).isoformat()}
    assert api_client.get(DAILY_URL, too_long).status_code == 400
    assert api_client.get(DAILY_URL, {"start": day.isoformat(), "end": day.isoformat()}).status_code == 400
    assert api_client.get(DAILY_URL, {"start": "not-a-date", "end": day.isoformat()}).status_code == 400


def test_day_endpoint_lists_free_vehicles_without_booking_details(api_client, other_user, fleet, day):
    book(other_user, fleet[0], at(day, 8), at(day, 10), purpose="Secret trip")
    response = api_client.get(DAY_URL, {"date": day.isoformat()})
    assert response.status_code == 200
    assert response.data["available"] == 2 and response.data["total"] == 3
    assert [v["plate_number"] for v in response.data["free_vehicles"]] == ["SAB-2000", "SAB-3000"]
    body = response.content.decode()
    for leaked in ("Secret", other_user.email, "start_time", "requester", "purpose"):
        assert leaked not in body


def test_day_endpoint_requires_date(api_client):
    assert api_client.get(DAY_URL).status_code == 400
