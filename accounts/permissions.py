"""DRF permission classes for the RBAC roles. Failing them returns 403."""

from rest_framework.permissions import BasePermission

from .models import Role
from .services.account_service import role_of


class IsAdminRole(BasePermission):
    message = "Only Admins can do this."

    def has_permission(self, request, view):
        return role_of(request.user) == Role.ADMIN


class IsStaffRole(BasePermission):
    """Admin or Scheduler."""

    message = "Only Admins and Schedulers can do this."

    def has_permission(self, request, view):
        return role_of(request.user) in (Role.ADMIN, Role.SCHEDULER)
