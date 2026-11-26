"""HTTP layer: parse/validate input, call the service, shape the response.

Status codes: 400 invalid input, 401 not authenticated, 403 wrong role,
409 slot conflict, 429 rate limited, 503 database unavailable (see
api/exceptions.py).

Visibility (RBAC): Users never receive other people's reservations, times
or conflict details, only daily free-vehicle counts. Admins and Schedulers
see everyone's schedule.
"""

from datetime import timedelta

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.services.account_service import is_staff_role

from ..models import Vehicle
from ..services import (
    ReservationValidationError,
    VehicleReservationService,
    VehicleUnavailableError,
)
from .serializers import (
    AvailabilityRangeSerializer,
    CalendarQuerySerializer,
    ConflictSerializer,
    DayQuerySerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    TimeRangeSerializer,
    VehicleSerializer,
    day_summary,
    to_calendar_event,
)


def _validation_error_response(exc):
    key = exc.field or "non_field_errors"
    return Response({key: [exc.message]}, status=status.HTTP_400_BAD_REQUEST)


def _conflict_response(exc, viewer):
    body = {"detail": exc.message, "code": "vehicle_unavailable"}
    if is_staff_role(viewer):
        body["conflicts"] = ConflictSerializer(exc.conflicts, many=True).data
    return Response(body, status=status.HTTP_409_CONFLICT)


class VehicleListView(generics.ListAPIView):
    """GET /api/vehicles/ — active vehicles that can be reserved."""

    serializer_class = VehicleSerializer
    queryset = Vehicle.objects.filter(is_active=True)
    pagination_class = None


class VehicleAvailabilityView(APIView):
    """GET /api/vehicles/<id>/availability/?start_time=..&end_time=.."""

    def get(self, request, vehicle_id):
        if not Vehicle.objects.filter(pk=vehicle_id, is_active=True).exists():
            return Response({"detail": "Vehicle not found."}, status=status.HTTP_404_NOT_FOUND)

        query = TimeRangeSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            available, conflicts = VehicleReservationService.check_availability(
                vehicle_id, query.validated_data["start_time"], query.validated_data["end_time"]
            )
        except ReservationValidationError as exc:
            return _validation_error_response(exc)

        body = {"vehicle": vehicle_id, "available": available}
        if is_staff_role(request.user):
            body["conflicts"] = ConflictSerializer(conflicts, many=True).data
        return Response(body)


class ReservationCreateView(APIView):
    """POST /api/reservations/ — submit a reservation request (F-01).

    Rate-limited per user (429 Too Many Requests) to stop request flooding.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reservation_create"

    def post(self, request):
        payload = ReservationCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            reservation = VehicleReservationService.create_reservation(
                requester=request.user,
                vehicle_id=data["vehicle"].pk,
                start_time=data["start_time"],
                end_time=data["end_time"],
                purpose=data["purpose"],
            )
        except ReservationValidationError as exc:
            return _validation_error_response(exc)
        except VehicleUnavailableError as exc:
            return _conflict_response(exc, request.user)

        return Response(ReservationSerializer(reservation).data, status=status.HTTP_201_CREATED)


class CalendarEventsView(APIView):
    """GET /api/calendar/events/?start=..&end=..[&vehicle=..] — FullCalendar feed.

    Admin/Scheduler: everyone's reservations. User: only their own.
    """

    def get(self, request):
        query = CalendarQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        staff = is_staff_role(request.user)
        reservations = VehicleReservationService.calendar_reservations(
            query.validated_data["start"],
            query.validated_data["end"],
            query.validated_data.get("vehicle"),
            requester=None if staff else request.user,
        )
        # FullCalendar expects a bare JSON array.
        return Response([to_calendar_event(r, request.user, show_details=staff) for r in reservations])


class DailyAvailabilityView(APIView):
    """GET /api/availability/?start=YYYY-MM-DD&end=YYYY-MM-DD (end exclusive).

    [{"date", "total", "available"}] per day: counts only, for every role.
    """

    def get(self, request):
        query = AvailabilityRangeSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            days = VehicleReservationService.daily_availability(
                query.validated_data["start"], query.validated_data["end"] - timedelta(days=1)
            )
        except ReservationValidationError as exc:
            return _validation_error_response(exc)
        return Response([day_summary(d) for d in days])


class DayAvailabilityView(APIView):
    """GET /api/availability/day/?date=YYYY-MM-DD.

    Count plus the list of vehicles still free that day (no booking details).
    """

    def get(self, request):
        query = DayQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        day = query.validated_data["date"]
        (result,) = VehicleReservationService.daily_availability(day, day)
        return Response(
            {**day_summary(result), "free_vehicles": VehicleSerializer(result.free_vehicles, many=True).data}
        )
