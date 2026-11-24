from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from reservations.models import Reservation
from reservations.services import (
    ReservationValidationError,
    VehicleReservationService,
    VehicleUnavailableError,
)

pytestmark = pytest.mark.django_db


def create(user, vehicle, start, end, purpose="Field inspection"):
    return VehicleReservationService.create_reservation(
        requester=user, vehicle_id=vehicle.pk, start_time=start, end_time=end, purpose=purpose
    )


def test_create_reservation_is_pending(user, vehicle, slot):
    reservation = create(user, vehicle, *slot)
    assert reservation.status == Reservation.Status.PENDING
    assert reservation.requester == user


@pytest.mark.parametrize(
    "offset_start, offset_end",
    [
        (timedelta(hours=1), timedelta(hours=2)),    # inside
        (timedelta(hours=-1), timedelta(hours=1)),   # overlaps start
        (timedelta(hours=2), timedelta(hours=5)),    # overlaps end
        (timedelta(hours=-1), timedelta(hours=4)),   # covers whole slot
        (timedelta(0), timedelta(hours=3)),          # identical
    ],
)
def test_overlap_is_rejected(user, other_user, vehicle, slot, offset_start, offset_end):
    start, _ = slot
    create(user, vehicle, *slot)
    with pytest.raises(VehicleUnavailableError) as exc:
        create(other_user, vehicle, start + offset_start, start + offset_end)
    assert len(exc.value.conflicts) == 1


def test_back_to_back_reservations_are_allowed(user, vehicle, slot):
    start, end = slot
    create(user, vehicle, start, end)
    create(user, vehicle, end, end + timedelta(hours=1))
    create(user, vehicle, start - timedelta(hours=1), start)
    assert Reservation.objects.count() == 3


def test_other_vehicle_same_slot_is_allowed(user, vehicle, slot):
    from reservations.models import Vehicle

    second = Vehicle.objects.create(plate_number="SAB-5678", name="Mitsubishi L300")
    create(user, vehicle, *slot)
    create(user, second, *slot)


@pytest.mark.parametrize(
    "status", [Reservation.Status.REJECTED, Reservation.Status.CANCELLED, Reservation.Status.COMPLETED]
)
def test_non_blocking_status_frees_the_slot(user, vehicle, slot, status):
    first = create(user, vehicle, *slot)
    first.status = status
    first.save()
    create(user, vehicle, *slot)


def test_end_before_start_rejected(user, vehicle, slot):
    start, end = slot
    with pytest.raises(ReservationValidationError) as exc:
        create(user, vehicle, end, start)
    assert exc.value.field == "end_time"


def test_past_start_rejected(user, vehicle):
    start = timezone.now() - timedelta(hours=1)
    with pytest.raises(ReservationValidationError) as exc:
        create(user, vehicle, start, start + timedelta(hours=2))
    assert exc.value.field == "start_time"


def test_too_long_rejected(user, vehicle, slot):
    start, _ = slot
    with pytest.raises(ReservationValidationError):
        create(user, vehicle, start, start + timedelta(days=8))


def test_more_than_six_months_ahead_rejected(user, vehicle):
    start = timezone.now() + timedelta(days=184)
    with pytest.raises(ReservationValidationError) as exc:
        create(user, vehicle, start, start + timedelta(hours=2))
    assert exc.value.field == "start_time"


def test_within_six_months_allowed(user, vehicle):
    start = timezone.now() + timedelta(days=182)
    create(user, vehicle, start, start + timedelta(hours=2))


def test_inactive_vehicle_rejected(user, vehicle, slot):
    vehicle.is_active = False
    vehicle.save()
    with pytest.raises(ReservationValidationError) as exc:
        create(user, vehicle, *slot)
    assert exc.value.field == "vehicle"


def test_blank_purpose_rejected(user, vehicle, slot):
    with pytest.raises(ReservationValidationError):
        create(user, vehicle, *slot, purpose="   ")


def test_database_exclusion_constraint_blocks_overlap_without_service(user, vehicle, slot):
    """Backstop: even raw ORM writes that skip the service cannot double-book."""
    start, end = slot
    Reservation.objects.create(requester=user, vehicle=vehicle, start_time=start, end_time=end, purpose="a")
    with pytest.raises(IntegrityError), transaction.atomic():
        Reservation.objects.create(
            requester=user, vehicle=vehicle,
            start_time=start + timedelta(hours=1), end_time=end + timedelta(hours=1), purpose="b",
        )


def test_database_check_constraint_blocks_inverted_range(user, vehicle, slot):
    start, end = slot
    with pytest.raises(IntegrityError), transaction.atomic():
        Reservation.objects.create(requester=user, vehicle=vehicle, start_time=end, end_time=start, purpose="x")


def test_check_availability(user, vehicle, slot):
    start, end = slot
    available, conflicts = VehicleReservationService.check_availability(vehicle.pk, start, end)
    assert available and conflicts == []
    create(user, vehicle, start, end)
    available, conflicts = VehicleReservationService.check_availability(vehicle.pk, start, end)
    assert not available and len(conflicts) == 1
