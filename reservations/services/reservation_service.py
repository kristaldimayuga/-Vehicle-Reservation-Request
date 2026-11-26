"""Business-logic layer for F-01 Vehicle Reservation Request.

Double-booking is prevented on two levels:
1. The vehicle row is locked with SELECT ... FOR UPDATE inside a short
   transaction, so concurrent requests for the same vehicle are serialized
   and the overlap check sees committed data.
2. A PostgreSQL exclusion constraint (`reservation_no_overlap`) rejects any
   overlap that slips past the application check.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Reservation, Vehicle
from .exceptions import ReservationValidationError, VehicleUnavailableError

OVERLAP_CONSTRAINT = "reservation_no_overlap"


@dataclass
class DayAvailability:
    """How many active vehicles are free on one local (Asia/Manila) day."""

    day: date
    vehicles: list  # all active vehicles
    taken_ids: set = field(default_factory=set)

    @property
    def total(self):
        return len(self.vehicles)

    @property
    def free_vehicles(self):
        return [v for v in self.vehicles if v.pk not in self.taken_ids]

    @property
    def available(self):
        return self.total - len(self.taken_ids)


class VehicleReservationService:
    MAX_DURATION = timedelta(days=7)
    MAX_ADVANCE = timedelta(days=183)  # ~6 months
    MAX_AVAILABILITY_DAYS = 62

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
    def calendar_reservations(range_start, range_end, vehicle_id=None, requester=None):
        """Slot-occupying reservations visible in a calendar window.

        `requester` limits the result to one user's own reservations (the
        caller decides this from the viewer's role).
        """
        qs = Reservation.objects.select_related("vehicle", "requester").filter(
            status__in=Reservation.BLOCKING_STATUSES,
            start_time__lt=range_end,
            end_time__gt=range_start,
        )
        if vehicle_id is not None:
            qs = qs.filter(vehicle_id=vehicle_id)
        if requester is not None:
            qs = qs.filter(requester=requester)
        return qs

    @classmethod
    def daily_availability(cls, first_day, last_day):
        """Free-vehicle count for each local day in [first_day, last_day].

        A vehicle counts as taken for a day if any slot-occupying reservation
        overlaps that day (00:00-24:00 local time). Only counts are exposed,
        never who booked or when.
        """
        if last_day < first_day:
            raise ReservationValidationError("End date must not be before start date.", field="end")
        if (last_day - first_day).days + 1 > cls.MAX_AVAILABILITY_DAYS:
            raise ReservationValidationError(
                f"Availability can be requested for at most {cls.MAX_AVAILABILITY_DAYS} days.", field="end"
            )

        tz = timezone.get_current_timezone()
        range_start = timezone.make_aware(datetime.combine(first_day, time.min), tz)
        range_end = timezone.make_aware(datetime.combine(last_day + timedelta(days=1), time.min), tz)

        vehicles = list(Vehicle.objects.filter(is_active=True).order_by("plate_number"))
        taken = defaultdict(set)
        rows = Reservation.objects.filter(
            vehicle__is_active=True,
            status__in=Reservation.BLOCKING_STATUSES,
            start_time__lt=range_end,
            end_time__gt=range_start,
        ).values_list("vehicle_id", "start_time", "end_time")
        for vehicle_id, start, end in rows:
            # End is exclusive: a booking ending exactly at midnight does not
            # occupy the next day.
            day = max(timezone.localtime(start, tz).date(), first_day)
            last = min(timezone.localtime(end - timedelta(microseconds=1), tz).date(), last_day)
            while day <= last:
                taken[day].add(vehicle_id)
                day += timedelta(days=1)

        days = []
        day = first_day
        while day <= last_day:
            days.append(DayAvailability(day=day, vehicles=vehicles, taken_ids=taken.get(day, set())))
            day += timedelta(days=1)
        return days

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
