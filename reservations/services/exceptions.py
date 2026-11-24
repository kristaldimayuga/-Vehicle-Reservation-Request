"""Domain exceptions raised by the service layer.

They are HTTP-agnostic; the API layer maps them to status codes
(ReservationValidationError -> 400, VehicleUnavailableError -> 409).
"""


class ReservationError(Exception):
    """Base class for reservation business-rule failures."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class ReservationValidationError(ReservationError):
    """Request violates a business rule (bad time range, inactive vehicle, ...)."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


class VehicleUnavailableError(ReservationError):
    """Vehicle already has an overlapping reservation for the requested slot."""

    def __init__(self, message, conflicts=()):
        super().__init__(message)
        self.conflicts = list(conflicts)
