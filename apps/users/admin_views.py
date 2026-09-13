import logging

from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import IsAdmin

from .models import User
from .serializers import AdminFanListSerializer, AdminUserListSerializer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed ordering fields — ONLY indexed columns to keep ORDER BY fast
# on large tables.  Prefix with "-" for descending.
# ---------------------------------------------------------------------------
_ALLOWED_ORDER_FIELDS = {
    "email", "-email",
    "role", "-role",
    "created_at", "-created_at",
    "is_active", "-is_active",
    "is_captain", "-is_captain",
}

_DEFAULT_ORDERING = "-created_at"


def _build_user_queryset(query_params):
    """
    Build and return an optimised User queryset for the admin list endpoint.

    Supported query params
    ─────────────────────
    email      (str)  — case-insensitive partial match on User.email
    role       (str)  — exact match: 'admin' | 'player'
    is_active  (bool) — 'true' | 'false'
    is_captain (bool) — 'true' | 'false'
    ordering   (str)  — field name, prefix '-' for DESC
                        allowed: email, role, created_at, is_active, is_captain

    All profile + team fields are resolved in a single query via
    select_related — no additional DB hits per row.
    """
    qs = (
        User.objects
        .select_related("profile__team", "waiver_signature")
        .order_by(_DEFAULT_ORDERING)
    )

    # --- Email search (partial, case-insensitive) ---
    email_param = query_params.get("email", "").strip()
    if email_param:
        qs = qs.filter(email__icontains=email_param)

    # --- Role filter ---
    role_param = query_params.get("role", "").strip()
    if role_param:
        valid_roles = {r[0] for r in User.Role.choices}
        if role_param not in valid_roles:
            raise ValidationError(
                {"role": f"Invalid role '{role_param}'. "
                         f"Valid values: {sorted(valid_roles)}."}
            )
        qs = qs.filter(role=role_param)

    # --- Boolean: is_active ---
    is_active_param = query_params.get("is_active", "").strip().lower()
    if is_active_param:
        if is_active_param not in {"true", "false"}:
            raise ValidationError(
                {"is_active": "Must be 'true' or 'false'."}
            )
        qs = qs.filter(is_active=(is_active_param == "true"))

    # --- Boolean: is_captain ---
    is_captain_param = query_params.get("is_captain", "").strip().lower()
    if is_captain_param:
        if is_captain_param not in {"true", "false"}:
            raise ValidationError(
                {"is_captain": "Must be 'true' or 'false'."}
            )
        qs = qs.filter(is_captain=(is_captain_param == "true"))

    # --- Ordering (validated against whitelist) ---
    ordering_param = query_params.get("ordering", "").strip()
    if ordering_param:
        if ordering_param not in _ALLOWED_ORDER_FIELDS:
            raise ValidationError(
                {"ordering": f"Invalid ordering '{ordering_param}'. "
                             f"Allowed: {sorted(_ALLOWED_ORDER_FIELDS)}."}
            )
        qs = qs.order_by(ordering_param)

    return qs


class AdminUserListView(generics.ListAPIView):
    """
    GET /admin/users/

    Paginated list of all registered users with optional filtering and
    ordering — admin only.

    The queryset resolves profile + team in a single JOIN via select_related,
    keeping total queries at 2 (count + data page) regardless of page size.

    Query params
    ────────────
    email      — partial email search (icontains)
    role       — exact: admin | player
    is_active  — true | false
    is_captain — true | false
    ordering   — email | -email | role | -role | created_at | -created_at |
                 is_active | -is_active | is_captain | -is_captain
    page       — page number (default 1)
    page_size  — results per page (default 20, max 100)

    Permission: IsAdmin (authenticated admins only).
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdminUserListSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        return _build_user_queryset(self.request.query_params)


# ---------------------------------------------------------------------------
# Fans
# ---------------------------------------------------------------------------

_FAN_ALLOWED_ORDER_FIELDS = {
    "email", "-email",
    "created_at", "-created_at",
}

_FAN_DEFAULT_ORDERING = "-created_at"


class AdminFanListView(generics.ListAPIView):
    """
    GET /admin/fans/

    Paginated list of all registered fan accounts — admin only. Surfaces
    favorite division, zip code, and how each fan signs in (Google, Apple,
    both, or email + password) so admins can see OAuth adoption at a glance.

    Query params
    ────────────
    search       — partial match on email or name (icontains)
    auth_method  — google | apple | email  (google/apple also match
                   accounts linked to both providers)
    division     — north | south
    ordering     — email | -email | created_at | -created_at
    page / page_size — standard pagination

    Permission: IsAdmin (authenticated admins only).
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdminFanListSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        query_params = self.request.query_params
        qs = (
            User.objects
            .filter(role=User.Role.FAN)
            .select_related("fan_profile")
            .order_by(_FAN_DEFAULT_ORDERING)
        )

        search = query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(email__icontains=search) | Q(name__icontains=search))

        auth_method = query_params.get("auth_method", "").strip().lower()
        if auth_method == "google":
            qs = qs.filter(google_id__isnull=False)
        elif auth_method == "apple":
            qs = qs.filter(apple_id__isnull=False)
        elif auth_method == "email":
            qs = qs.filter(google_id__isnull=True, apple_id__isnull=True)
        elif auth_method:
            raise ValidationError(
                {"auth_method": "Must be 'google', 'apple', or 'email'."}
            )

        division = query_params.get("division", "").strip().lower()
        if division:
            valid_divisions = {"north", "south"}
            if division not in valid_divisions:
                raise ValidationError(
                    {"division": f"Invalid division '{division}'. Valid values: {sorted(valid_divisions)}."}
                )
            qs = qs.filter(fan_profile__favorite_division=division)

        ordering = query_params.get("ordering", "").strip()
        if ordering:
            if ordering not in _FAN_ALLOWED_ORDER_FIELDS:
                raise ValidationError(
                    {"ordering": f"Invalid ordering '{ordering}'. Allowed: {sorted(_FAN_ALLOWED_ORDER_FIELDS)}."}
                )
            qs = qs.order_by(ordering)

        return qs
