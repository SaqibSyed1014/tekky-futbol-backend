import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import IsAdmin, IsPlayer

from .models import Application
from .serializers import (
    AdminApplicationFlatSerializer,
    ApplicationCreateSerializer,
    ApplicationSerializer,
    ApplicationStatusUpdateSerializer,
    PublicApplicationSerializer,
)
from .services import ApplicationService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_queryset(qs, query_params):
    """
    Apply optional query-string filters to an Application queryset.

    Supported params
    ────────────────
    status  — one of Application.Status choices (exact)
    type    — one of Application.Type choices   (exact, admin only)
    email   — partial match on applicant.email  (icontains, admin only)

    Invalid choice values raise 400 immediately so the client gets
    actionable feedback instead of a silent empty result.
    """
    from rest_framework.exceptions import ValidationError

    # --- Status filter ---
    status_param = query_params.get("status", "").strip()
    if status_param:
        valid_statuses = {s[0] for s in Application.Status.choices}
        if status_param not in valid_statuses:
            raise ValidationError(
                {"status": f"Invalid status '{status_param}'. "
                           f"Valid values: {sorted(valid_statuses)}."}
            )
        qs = qs.filter(status=status_param)

    # --- Type filter ---
    type_param = query_params.get("type", "").strip()
    if type_param:
        valid_types = {t[0] for t in Application.Type.choices}
        if type_param not in valid_types:
            raise ValidationError(
                {"type": f"Invalid type '{type_param}'. "
                         f"Valid values: {sorted(valid_types)}."}
            )
        qs = qs.filter(type=type_param)

    # --- Applicant email search (partial, case-insensitive) ---
    email_param = query_params.get("email", "").strip()
    if email_param:
        qs = qs.filter(applicant__email__icontains=email_param)

    return qs


# ---------------------------------------------------------------------------
# Root dispatcher — GET /applications (admin list) | POST /applications (public)
# ---------------------------------------------------------------------------


class ApplicationRootView(APIView):
    """
    Dispatches based on HTTP method:

        GET  → FrontendAdminApplicationListView  (admin required)
        POST → PublicApplicationCreateView       (no auth required)

    This lets the frontend call the same path for both the registration
    form and the admin dashboard list.
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsAdmin()]
        return []  # POST is public

    def get(self, request: Request) -> Response:
        return FrontendAdminApplicationListView().get(request)

    def post(self, request: Request) -> Response:
        return PublicApplicationCreateView().post(request)


# ---------------------------------------------------------------------------
# Public — POST /applications  (no auth required)
# ---------------------------------------------------------------------------


class PublicApplicationCreateView(APIView):
    """
    Public registration endpoint consumed by the frontend multi-step form.

    Creates a User + PlayerProfile + Application in one atomic transaction.
    No JWT token required — this is the entry point for new participants.

    Payload (camelCase, matching the frontend):
        applicationType, name, email, phone, gender, preferredDivision,
        instagram (optional), reasonForCompeting,
        teamName + rosterSize (full_team only),
        nameLogoConfirmation, nonGuarantee, codeOfConduct
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = PublicApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        application = ApplicationService.register_and_apply(serializer.validated_data)

        logger.info(
            "Public registration submitted: application=%s type=%s",
            application.id, application.type,
        )
        return Response(
            ApplicationSerializer(application).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Player — POST /applications  (authenticated, legacy / internal use)
# ---------------------------------------------------------------------------


class CreateApplicationView(APIView):
    """
    Submit a new application (player only).

    - type='captain'    → metadata.team_name required; no team field.
    - type='free_agent' → team (UUID) required.

    Duplicate pending applications of the same type are rejected by the
    service layer (ApplicationService.create_application).

    Permission: authenticated players only.
    """

    permission_classes = [IsAuthenticated, IsPlayer]

    def post(self, request: Request) -> Response:
        serializer = ApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        application = ApplicationService.create_application(
            applicant=request.user,
            app_type=serializer.validated_data["type"],
            team=serializer.validated_data.get("team"),
            message=serializer.validated_data.get("message"),
            metadata=serializer.validated_data.get("metadata", {}),
        )

        logger.info(
            "Application %s created by player %s",
            application.id, request.user.id,
        )
        return Response(
            ApplicationSerializer(application).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Player — GET /applications/me
# ---------------------------------------------------------------------------


class PlayerApplicationListView(generics.ListAPIView):
    """
    List the authenticated player's own applications.

    Filter params:
        status — pending | approved | rejected | waitlist | interview
        type   — captain | free_agent

    Ordered by newest first. Paginated.

    Permission: authenticated players only.
    """

    permission_classes = [IsAuthenticated, IsPlayer]
    serializer_class = ApplicationSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = (
            Application.objects
            .filter(applicant=self.request.user)
            .select_related("applicant", "applicant__profile", "team", "reviewed_by")
            .order_by("-created_at")
        )
        return _filter_queryset(qs, self.request.query_params)


# ---------------------------------------------------------------------------
# Admin — GET /admin/applications
# ---------------------------------------------------------------------------


class AdminApplicationListView(generics.ListAPIView):
    """
    List all applications across the platform (admin only).

    Filter params:
        status — pending | approved | rejected | waitlist | interview
        type   — captain | free_agent

    Ordered by newest first. Paginated.

    Permission: authenticated admins only.
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = ApplicationSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = (
            Application.objects
            .select_related("applicant", "team", "reviewed_by")
            .order_by("-created_at")
        )
        return _filter_queryset(qs, self.request.query_params)


# ---------------------------------------------------------------------------
# Admin — PATCH /admin/applications/{id}
# ---------------------------------------------------------------------------


class AdminApplicationUpdateView(APIView):
    """
    Update the status of a specific application (admin only).

    Validates the requested transition at the serializer level, then
    delegates the full state-machine check and any approval side-effects
    to ApplicationService.update_application_status.

    Approval side-effects:
        captain    → TeamService.create_team is called automatically.
        free_agent → PlayerService.assign_player_to_team is called automatically.

    Request body:
        { "status": "<new_status>", "admin_notes": "<optional notes>" }

    Permission: authenticated admins only.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def patch(self, request: Request, pk) -> Response:
        application = get_object_or_404(
            Application.objects.select_related("applicant", "team", "reviewed_by"),
            pk=pk,
        )

        # Inject the current application instance into context so the
        # serializer can enforce the terminal-state guard without a DB call.
        serializer = ApplicationStatusUpdateSerializer(
            data=request.data,
            context={"application": application},
        )
        serializer.is_valid(raise_exception=True)

        updated = ApplicationService.update_application_status(
            application=application,
            new_status=serializer.validated_data["status"],
            reviewed_by=request.user,
            admin_notes=serializer.validated_data.get("admin_notes"),
        )

        logger.info(
            "Application %s updated to '%s' by admin %s",
            updated.id, updated.status, request.user.id,
        )
        return Response(
            ApplicationSerializer(updated).data,
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Frontend admin dashboard — GET /applications  (camelCase, paginated)
# ---------------------------------------------------------------------------


class FrontendAdminApplicationListView(APIView):
    """
    Paginated list of ALL applications for the admin dashboard frontend.

    URL: GET /api/v1/applications/?page=1&limit=20&status=pending

    Response shape matches what AdminClient.js expects:
        {
          "data":  [ { id, name, email, applicationType, preferredDivision,
                       status, createdAt }, ... ],
          "total": <int>,
          "page":  <int>,
          "limit": <int>
        }

    Permission: authenticated admins only.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request) -> Response:
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (ValueError, TypeError):
            page = 1

        try:
            limit = min(100, max(1, int(request.query_params.get("limit", 20))))
        except (ValueError, TypeError):
            limit = 20

        qs = (
            Application.objects
            .select_related("applicant__profile", "team")
            .order_by("-created_at")
        )

        # Optional status filter
        status_param = request.query_params.get("status", "").strip()
        if status_param:
            from rest_framework.exceptions import ValidationError
            valid_statuses = {s[0] for s in Application.Status.choices}
            if status_param not in valid_statuses:
                raise ValidationError(
                    {"status": f"Invalid status '{status_param}'. "
                               f"Valid values: {sorted(valid_statuses)}."}
                )
            qs = qs.filter(status=status_param)

        total = qs.count()
        offset = (page - 1) * limit
        applications = qs[offset: offset + limit]

        return Response({
            "data": AdminApplicationFlatSerializer(applications, many=True).data,
            "total": total,
            "page": page,
            "limit": limit,
        }, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Frontend admin dashboard — PATCH /applications/:id/approve
#                            PATCH /applications/:id/reject
# ---------------------------------------------------------------------------


class FrontendApproveApplicationView(APIView):
    """
    PATCH /applications/:id/approve

    One-click approve for the admin dashboard. Transitions the application
    to 'approved' and triggers the appropriate side-effect (team creation
    or player assignment).

    Returns the updated application in the flat camelCase format so the
    frontend can directly replace the row in its local state.

    Permission: authenticated admins only.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def patch(self, request: Request, pk) -> Response:
        application = get_object_or_404(
            Application.objects.select_related("applicant__profile", "team", "reviewed_by"),
            pk=pk,
        )
        updated = ApplicationService.update_application_status(
            application=application,
            new_status=Application.Status.APPROVED,
            reviewed_by=request.user,
        )
        logger.info("Application %s approved by admin %s", updated.id, request.user.id)
        return Response(
            AdminApplicationFlatSerializer(updated).data,
            status=status.HTTP_200_OK,
        )


class FrontendRejectApplicationView(APIView):
    """
    PATCH /applications/:id/reject

    One-click reject for the admin dashboard.

    Accepts optional body:  { "reason": "..." }
    Stored as admin_notes on the application.

    Returns the updated application in the flat camelCase format.

    Permission: authenticated admins only.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def patch(self, request: Request, pk) -> Response:
        application = get_object_or_404(
            Application.objects.select_related("applicant__profile", "team", "reviewed_by"),
            pk=pk,
        )
        reason = request.data.get("reason", "")
        updated = ApplicationService.update_application_status(
            application=application,
            new_status=Application.Status.REJECTED,
            reviewed_by=request.user,
            admin_notes=reason or None,
        )
        logger.info("Application %s rejected by admin %s", updated.id, request.user.id)
        return Response(
            AdminApplicationFlatSerializer(updated).data,
            status=status.HTTP_200_OK,
        )
