import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import IsAdmin

from .models import WaiverSignature
from .serializers import (
    AdminWaiverDetailSerializer,
    AdminWaiverListSerializer,
    WaiverSignatureCreateSerializer,
    WaiverStatusSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Player / Captain — sign + read own waiver
# ---------------------------------------------------------------------------

class WaiverMeView(APIView):
    """
    GET  /api/v1/waivers/me/  — returns the current user's waiver status,
                                 or 404 if they have not signed yet.
    POST /api/v1/waivers/me/  — submit the signed waiver form.
                                 Idempotent: re-posting returns 200 with existing record.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            sig = request.user.waiver_signature
        except WaiverSignature.DoesNotExist:
            return Response(
                {"waiver_signed": False},
                status=status.HTTP_200_OK,
            )
        return Response({
            "waiver_signed": True,
            **WaiverStatusSerializer(sig).data,
        })

    def post(self, request):
        # Already signed — return existing record (idempotent)
        try:
            existing = request.user.waiver_signature
            return Response(
                {"waiver_signed": True, **WaiverStatusSerializer(existing).data},
                status=status.HTTP_200_OK,
            )
        except WaiverSignature.DoesNotExist:
            pass

        serializer = WaiverSignatureCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Capture request metadata for the audit trail
        ip = (
            request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")
        )
        ua = request.META.get("HTTP_USER_AGENT", "")

        sig = WaiverSignature.objects.create(
            user=request.user,
            date_of_birth=d.get("date_of_birth"),
            address=d.get("address", ""),
            participant_phone=d.get("participant_phone", ""),
            medical_conditions=d.get("medical_conditions", ""),
            emergency_contact_name=d.get("emergency_contact_name", ""),
            emergency_contact_rel=d.get("emergency_contact_rel", ""),
            emergency_contact_phone=d.get("emergency_contact_phone", ""),
            clauses_initialed=d["clauses_initialed"],
            is_minor=d.get("is_minor", False),
            printed_name=d.get("printed_name", ""),
            signature_image=d.get("signature_image", ""),
            guardian_signature=d.get("guardian_signature", ""),
            guardian_name_printed=d.get("guardian_name_printed", ""),
            guardian_email=d.get("guardian_email", ""),
            guardian_phone=d.get("guardian_phone", ""),
            guardian_type=d.get("guardian_type", ""),
            ip_address=ip or None,
            user_agent=ua,
        )

        logger.info("Waiver signed: user=%s version=%s", request.user.id, sig.waiver_version)

        return Response(
            {"waiver_signed": True, **WaiverStatusSerializer(sig).data},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Admin — list all signed waivers + unsigned users
# ---------------------------------------------------------------------------

class AdminWaiverSignedListView(generics.ListAPIView):
    """
    GET /api/v1/admin/waivers/signed/

    Lists all users who have signed the waiver.
    Supports filter: ?role=player|captain|admin
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class   = AdminWaiverListSerializer
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        qs = WaiverSignature.objects.select_related("user").order_by("-signed_at")

        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(user__role=role)

        is_captain = self.request.query_params.get("is_captain")
        if is_captain == "true":
            qs = qs.filter(user__is_captain=True)
        elif is_captain == "false":
            qs = qs.filter(user__is_captain=False)

        return qs


class AdminWaiverUnsignedListView(generics.ListAPIView):
    """
    GET /api/v1/admin/waivers/unsigned/

    Lists all active users who have NOT yet signed the waiver.
    Supports filter: ?role=player|admin  and  ?is_captain=true
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        from apps.users.models import User
        signed_ids = WaiverSignature.objects.values_list("user_id", flat=True)
        # Only players/captains need to sign — exclude admin accounts.
        qs = (
            User.objects
            .filter(is_active=True, role=User.Role.PLAYER)
            .exclude(id__in=signed_ids)
            .order_by("-created_at")
        )

        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)

        is_captain = self.request.query_params.get("is_captain")
        if is_captain == "true":
            qs = qs.filter(is_captain=True)
        elif is_captain == "false":
            qs = qs.filter(is_captain=False)

        return qs

    def list(self, request, *args, **kwargs):
        from apps.users.serializers import AdminUserListSerializer
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = AdminUserListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = AdminUserListSerializer(qs, many=True)
        return Response(serializer.data)


class AdminWaiverDetailView(APIView):
    """
    GET /api/v1/admin/waivers/<user_id>/

    Returns the complete waiver record for the given user.
    Used by the admin "View Waiver" feature to display a read-only,
    pre-filled copy of the participant's signed form.

    Permission: IsAdmin only.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, user_id):
        try:
            sig = (
                WaiverSignature.objects
                .select_related("user")
                .get(user_id=user_id)
            )
        except WaiverSignature.DoesNotExist:
            return Response(
                {"detail": "No waiver found for this user."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(AdminWaiverDetailSerializer(sig).data)
