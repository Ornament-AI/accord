"""Structured error hierarchy.

All application errors extend AccordError. The exception handler in main.py
serializes them to the public RFC 9457 ProblemDetail JSON shape.
"""


class AccordError(Exception):
    status_code: int = 400
    error_code: str | None = None

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    @property
    def detail(self) -> str:
        return self.message

    @property
    def error(self) -> str:
        return self.error_code or type(self).__name__


class NotFoundError(AccordError):
    status_code = 404


class ValidationError(AccordError):
    status_code = 400


class ConflictError(AccordError):
    status_code = 409


STALE_ROW_DETAIL = "This row changed after you opened it. Reload the latest row and try again."


class StaleRowError(ConflictError):
    error_code = "stale_row"

    def __init__(self, message: str = STALE_ROW_DETAIL):
        super().__init__(message)


class StateError(AccordError):
    """Workflow state machine violations."""

    status_code = 400


class ForbiddenError(AccordError):
    status_code = 403
