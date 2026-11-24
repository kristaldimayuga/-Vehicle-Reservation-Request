from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("calendar/", views.calendar_page, name="calendar"),
]
