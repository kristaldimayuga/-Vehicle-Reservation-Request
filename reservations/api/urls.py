from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("vehicles/", views.VehicleListView.as_view(), name="vehicle-list"),
    path(
        "vehicles/<int:vehicle_id>/availability/",
        views.VehicleAvailabilityView.as_view(),
        name="vehicle-availability",
    ),
    path("reservations/", views.ReservationCreateView.as_view(), name="reservation-create"),
    path("calendar/events/", views.CalendarEventsView.as_view(), name="calendar-events"),
    path("availability/", views.DailyAvailabilityView.as_view(), name="daily-availability"),
    path("availability/day/", views.DayAvailabilityView.as_view(), name="day-availability"),
]
