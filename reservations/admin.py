from django.contrib import admin

from .models import Reservation, Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "name", "vehicle_type", "capacity", "is_active")
    list_filter = ("is_active", "vehicle_type")
    search_fields = ("plate_number", "name")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("id", "vehicle", "requester", "start_time", "end_time", "status")
    list_filter = ("status", "vehicle")
    search_fields = ("vehicle__plate_number", "requester__username", "purpose")
    date_hierarchy = "start_time"
    list_select_related = ("vehicle", "requester")
