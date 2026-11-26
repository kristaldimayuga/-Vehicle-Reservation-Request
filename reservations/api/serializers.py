"""Input parsing / output shaping only. Business rules live in services/."""

from django.utils import timezone
from rest_framework import serializers

from ..models import Reservation, Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ["id", "plate_number", "name", "vehicle_type", "capacity"]


class TimeRangeSerializer(serializers.Serializer):
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return attrs


class ReservationCreateSerializer(TimeRangeSerializer):
    vehicle = serializers.PrimaryKeyRelatedField(queryset=Vehicle.objects.all())
    purpose = serializers.CharField(max_length=500, trim_whitespace=True)


class ReservationSerializer(serializers.ModelSerializer):
    vehicle = VehicleSerializer(read_only=True)

    class Meta:
        model = Reservation
        fields = ["id", "vehicle", "start_time", "end_time", "purpose", "status", "created_at"]


class ConflictSerializer(serializers.ModelSerializer):
    """Conflict info safe to show any user: no requester or purpose."""

    class Meta:
        model = Reservation
        fields = ["start_time", "end_time", "status"]


class CalendarQuerySerializer(serializers.Serializer):
    # FullCalendar sends `start` and `end` query params automatically.
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    vehicle = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        if attrs["end"] <= attrs["start"]:
            raise serializers.ValidationError({"end": "End must be after start."})
        if (attrs["end"] - attrs["start"]).days > 62:
            raise serializers.ValidationError({"end": "Calendar window cannot exceed 62 days."})
        return attrs


class AvailabilityRangeSerializer(serializers.Serializer):
    # Local dates; `end` is exclusive (same convention as FullCalendar).
    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if attrs["end"] <= attrs["start"]:
            raise serializers.ValidationError({"end": "End must be after start."})
        return attrs


class DayQuerySerializer(serializers.Serializer):
    date = serializers.DateField()


def day_summary(day):
    """{date, total, available}: counts only, never who or when."""
    return {"date": day.day.isoformat(), "total": day.total, "available": day.available}


def to_calendar_event(reservation, viewer, *, show_details):
    """FullCalendar event object.

    Users only ever receive their own reservations. Admins/Schedulers
    (`show_details=True`) see everyone's, including requester and purpose.
    """
    is_own = reservation.requester_id == viewer.pk
    if is_own:
        who = "My reservation"
    else:
        who = reservation.requester.email or reservation.requester.get_username()
    event = {
        "id": reservation.pk,
        "title": f"{reservation.vehicle.plate_number} — {who}",
        # Local time (Asia/Manila, +08:00), consistent with DRF's DateTimeField
        # output on the other endpoints.
        "start": timezone.localtime(reservation.start_time).isoformat(),
        "end": timezone.localtime(reservation.end_time).isoformat(),
        "classNames": [f"status-{reservation.status.lower()}"] + (["own"] if is_own else []),
        "extendedProps": {
            "kind": "reservation",
            "vehicleId": reservation.vehicle_id,
            "status": reservation.status,
            "isOwn": is_own,
        },
    }
    if is_own or show_details:
        event["extendedProps"]["purpose"] = reservation.purpose
    if show_details:
        event["extendedProps"]["requester"] = reservation.requester.email
    return event
