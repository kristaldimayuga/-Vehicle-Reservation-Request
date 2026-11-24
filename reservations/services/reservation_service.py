"""Business-logic layer for F-01 Vehicle Reservation Request.

Double-booking is prevented on two levels:
1. The vehicle row is locked with SELECT ... FOR UPDATE inside a short
   transaction, so concurrent requests for the same vehicle are serialized
   and the overlap check sees committed data.
2. A PostgreSQL exclusion constraint (`reservation_no_overlap`) rejects any
   overlap that slips past the application check.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Reservation, Vehicle
from .exceptions import ReservationValidationError, VehicleUnavailableError

OVERLAP_CONSTRAINT = "reservation_no_overlap"


class VehicleReservationService:
    MAX_DURATION = timedelta(days=7)
    MAX_ADVANCE = timedelta(days=183)  # ~6 months

    # --- Queries ------------------------------------------------------------

    @staticmethod
    def find_conflicts(vehicle_id, start_time, end_time, exclude_id=None):
        """Slot-occupying reservations of `vehicle_id` overlapping [start, end)."""
        qs = Reservation.objects.filter(
            vehicle_id=vehicle_id,
            status__in=Reservation.BLOCKING_STATUSES,
            start_time__lt=end_time,
            end_time__gt=start_time,
        )
        if exclude_id is not None:
            qs = qs.exclude(pk=exclude_id)
        return qs

    @classmethod
    def check_availability(cls, vehicle_id, start_time, end_time):
        """Return (is_available, conflicts) without creating anything."""
        cls._validate_time_range(start_time, end_time)
        conflicts = list(cls.find_conflicts(vehicle_id, start_time, end_time))
        return not conflicts, conflicts

    @staticmethod
    def calendar_reservations(range_start, range_end, vehicle_id=None):
        """Slot-occupying reservations visible in a calendar window."""
        qs = Reservation.objects.select_related("vehicle").filter(
            status__in=Reservation.BLOCKING_STATUSES,
            start_time__lt=range_end,
            end_time__gt=range_start,
        )
        if vehicle_id is not None:
            qs = qs.filter(vehicle_id=vehicle_id)
        return qs

    # --- Commands -----------------------------------------------------------

    @classmethod
    def create_reservation(cls, *, requester, vehicle_id, start_time, end_time, purpose):
        """Create a PENDING reservation or raise a domain exception."""
        cls._validate_time_range(start_time, end_time)
        purpose = (purpose or "").strip()
        if not purpose:
            raise ReservationValidationError("Purpose is required.", field="purpose")

        with transaction.atomic():
            try:
                vehicle = Vehicle.objects.select_for_update().get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                raise ReservationValidationError("Vehicle does not exist.", field="vehicle")
            if not vehicle.is_active:
                raise ReservationValidationError(
                    "Vehicle is not available for reservation.", field="vehicle"
                )

            conflicts = list(cls.find_conflicts(vehicle.pk, start_time, end_time))
            if conflicts:
                raise VehicleUnavailableError(
                    "Vehicle is already reserved for the requested time slot.", conflicts
                )

            try:
                with transaction.atomic():
                    return Reservation.objects.create(
                        requester=requester,
                        vehicle=vehicle,
                        start_time=start_time,
                        end_time=end_time,
                        purpose=purpose,
                        status=Reservation.Status.PENDING,
                    )
            except IntegrityError as exc:
                if _violated_constraint(exc) == OVERLAP_CONSTRAINT:
                    raise VehicleUnavailableError(
                        "Vehicle is already reserved for the requested time slot."
                    ) from exc
                raise

    # --- Validation ---------------------------------------------------------

    @classmethod
    def _validate_time_range(cls, start_time, end_time):
        if start_time is None or end_time is None:
            raise ReservationValidationError("Start and end time are required.")
        if timezone.is_naive(start_time) or timezone.is_naive(end_time):
            raise ReservationValidationError("Timestamps must include a timezone.")
        if end_time <= start_time:
            raise ReservationValidationError(
                "End time must be after start time.", field="end_time"
            )
        now = timezone.now()
        if start_time < now:
            raise ReservationValidationError(
                "Start time cannot be in the past.", field="start_time"
            )
        if end_time - start_time > cls.MAX_DURATION:
            raise ReservationValidationError(
                "Reservations cannot exceed 7 days.", field="end_time"
            )
        if start_time > now + cls.MAX_ADVANCE:
            raise ReservationValidationError(
                "Reservations can be made at most 6 months in advance.", field="start_time"
            )


def _violated_constraint(exc):
    cause = exc.__cause__
    diag = getattr(cause, "diag", None)
    return getattr(diag, "constraint_name", None)
