"""HTTP layer: parse/validate input, call the service, shape the response.

Status codes: 400 invalid input, 401 not authenticated, 409 slot conflict,
429 rate limited, 503 database unavailable (see api/exceptions.py).
"""

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..models import Vehicle
from ..services import (
    ReservationValidationError,
    VehicleReservationService,
    VehicleUnavailableError,
)
from .serializers import (
    CalendarQuerySerializer,
    ConflictSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    TimeRangeSerializer,
    VehicleSerializer,
    to_calendar_event,
)


def _validation_error_response(exc):
    key = exc.field or "non_field_errors"
    return Response({key: [exc.message]}, status=status.HTTP_400_BAD_REQUEST)


def _conflict_response(exc):
    return Response(
        {
            "detail": exc.message,
            "code": "vehicle_unavailable",
            "conflicts": ConflictSerializer(exc.conflicts, many=True).data,
        },
        status=status.HTTP_409_CONFLICT,
    )


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

        return Response(
            {
                "vehicle": vehicle_id,
                "available": available,
                "conflicts": ConflictSerializer(conflicts, many=True).data,
            }
        )


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
            return _conflict_response(exc)

        return Response(ReservationSerializer(reservation).data, status=status.HTTP_201_CREATED)


class CalendarEventsView(APIView):
    """GET /api/calendar/events/?start=..&end=..[&vehicle=..] — FullCalendar feed."""

    def get(self, request):
        query = CalendarQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        reservations = VehicleReservationService.calendar_reservations(
            query.validated_data["start"],
            query.validated_data["end"],
            query.validated_data.get("vehicle"),
        )
        # FullCalendar expects a bare JSON array.
        return Response([to_calendar_event(r, request.user) for r in reservations])
