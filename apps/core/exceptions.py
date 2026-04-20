from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


# ---------------------------------------------------------------------------
# Domain exception hierarchy
# All service-layer errors inherit from DomainError so the DRF handler can
# catch them in one place and map them to the right HTTP status code.
# ---------------------------------------------------------------------------

class DomainError(Exception):
    """Base for all domain-level errors raised by the service layer."""


class InvalidRoleError(DomainError):
    """Operation is not permitted for the user's current role."""


class InvalidStatusTransitionError(DomainError):
    """Attempted status transition is not allowed by the state machine."""


class DuplicateApplicationError(DomainError):
    """User already has a pending application of this type."""


class TeamAlreadyExistsError(DomainError):
    """User already captains a team."""


class PlayerAlreadyOnTeamError(DomainError):
    """Player is already assigned to a team."""


class TeamCapacityExceededError(DomainError):
    """Team has reached its maximum player count."""


class ProfileNotFoundError(DomainError):
    """No PlayerProfile exists for this user."""


class ApplicationRequiresTeamError(DomainError):
    """A free_agent application must reference a target team."""


class MissingApplicationMetadataError(DomainError):
    """Required metadata key is absent from the application payload."""


# ---------------------------------------------------------------------------
# Domain error → HTTP status mapping
# ---------------------------------------------------------------------------

_DOMAIN_STATUS_MAP: dict[type[DomainError], int] = {
    InvalidRoleError: status.HTTP_403_FORBIDDEN,
    InvalidStatusTransitionError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    DuplicateApplicationError: status.HTTP_409_CONFLICT,
    TeamAlreadyExistsError: status.HTTP_409_CONFLICT,
    PlayerAlreadyOnTeamError: status.HTTP_409_CONFLICT,
    TeamCapacityExceededError: status.HTTP_409_CONFLICT,
    ProfileNotFoundError: status.HTTP_404_NOT_FOUND,
    ApplicationRequiresTeamError: status.HTTP_400_BAD_REQUEST,
    MissingApplicationMetadataError: status.HTTP_400_BAD_REQUEST,
}


# ---------------------------------------------------------------------------
# DRF exception handler
# ---------------------------------------------------------------------------

def custom_exception_handler(exc, context):
    """
    Normalise all errors — both DRF and domain — into a single JSON envelope:

        {"error": {"status_code": <int>, "detail": <str | dict>}}
    """
    # Intercept domain errors before DRF sees them
    if isinstance(exc, DomainError):
        http_status = _DOMAIN_STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return Response(
            {"error": {"status_code": http_status, "detail": str(exc)}},
            status=http_status,
        )

    if isinstance(exc, Http404):
        exc = exc.__class__(str(exc))
    elif isinstance(exc, PermissionDenied):
        pass  # let DRF convert to 403

    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "error": {
                "status_code": response.status_code,
                "detail": response.data,
            }
        }
        return response

    # Unhandled — return 500 without leaking a traceback
    return Response(
        {"error": {"status_code": 500, "detail": "Internal server error."}},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
