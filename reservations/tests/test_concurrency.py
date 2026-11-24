"""Race-condition test: many simultaneous requests for the same slot."""

import threading

import pytest
from django.db import connection

from reservations.models import Reservation
from reservations.services import VehicleReservationService, VehicleUnavailableError


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_for_same_slot_yield_one_booking(user, vehicle, slot):
    workers = 8
    barrier = threading.Barrier(workers)
    outcomes = []
    lock = threading.Lock()

    def attempt():
        try:
            barrier.wait()
            VehicleReservationService.create_reservation(
                requester=user, vehicle_id=vehicle.pk,
                start_time=slot[0], end_time=slot[1], purpose="Race",
            )
            result = "ok"
        except VehicleUnavailableError:
            result = "conflict"
        except Exception as exc:  # surface unexpected errors in the assertion
            result = f"error: {exc!r}"
        finally:
            connection.close()
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert outcomes.count("ok") == 1, outcomes
    assert outcomes.count("conflict") == workers - 1, outcomes
    assert Reservation.objects.filter(vehicle=vehicle).count() == 1
