"""Data layer for F-01 Vehicle Reservation Request."""

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q


class TsTzRange(Func):
    """SQL `tstzrange(start, end, '[)')` used by the overlap exclusion constraint."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Vehicle(models.Model):
    plate_number = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100, help_text="Make/model, e.g. 'Toyota Hiace'.")
    vehicle_type = models.CharField(max_length=50, blank=True)
    capacity = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(
        default=True, help_text="Inactive vehicles cannot be reserved."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["plate_number"]

    def __str__(self):
        return f"{self.plate_number} ({self.name})"


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        ONGOING = "ONGOING", "Ongoing"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    # Statuses that occupy the vehicle's time slot. Rejected/cancelled/completed
    # reservations free the slot again.
    BLOCKING_STATUSES = (Status.PENDING, Status.APPROVED, Status.ONGOING)

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservations"
    )
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="reservations")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    purpose = models.TextField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        indexes = [
            models.Index(fields=["vehicle", "start_time", "end_time"], name="resv_vehicle_time_idx"),
            models.Index(fields=["start_time"], name="resv_start_idx"),
            models.Index(fields=["end_time"], name="resv_end_idx"),
            models.Index(fields=["status"], name="resv_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="reservation_end_after_start",
            ),
            # Database-level guarantee against double-booking: no two
            # slot-occupying reservations for the same vehicle may overlap.
            # Half-open ranges '[)' let back-to-back bookings touch.
            ExclusionConstraint(
                name="reservation_no_overlap",
                expressions=[
                    (TsTzRange("start_time", "end_time", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("vehicle", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=["PENDING", "APPROVED", "ONGOING"]),
            ),
        ]

    def __str__(self):
        return f"#{self.pk} {self.vehicle.plate_number} {self.start_time:%Y-%m-%d %H:%M} [{self.status}]"
