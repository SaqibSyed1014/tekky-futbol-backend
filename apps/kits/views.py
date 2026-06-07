import csv
import logging

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin, IsCaptain
from apps.teams.models import Team, TeamMembership

from .email_service import send_kit_locked_email
from .models import KitOrder, TeamKitSelection
from .serializers import (
    AdminTeamKitSerializer,
    KitOrderSerializer,
    KitOrderSubmitSerializer,
    KitSelectSerializer,
    TeamKitSelectionSerializer,
)

logger = logging.getLogger(__name__)


def _get_approved_team(user) -> Team | None:
    """
    Return the team for the given user, or None if they are not attached to one.
    - Captains: via captained_team
    - Players: via approved TeamMembership
    """
    if user.is_captain:
        return getattr(user, "captained_team", None)

    profile = getattr(user, "profile", None)
    if profile and profile.team:
        is_approved = TeamMembership.objects.filter(
            user=user,
            team=profile.team,
            status=TeamMembership.Status.APPROVED,
        ).exists()
        if is_approved:
            return profile.team
    return None


# ---------------------------------------------------------------------------
# GET  /kits/my/         — any team member: see kit state + own order
# PATCH /kits/my/        — captain only: select / change kit (while unlocked)
# ---------------------------------------------------------------------------

class MyKitView(APIView):
    """
    GET  — Returns the team's current kit selection and the caller's own
           size order (if submitted). Works for both captains and players.

    PATCH — Captain selects or changes the kit slug.
            Rejected if the kit is already locked.
    """

    permission_classes = [IsAuthenticated]

    def _get_kit_data(self, request, team: Team) -> dict:
        kit_sel = getattr(team, "kit_selection", None)
        kit_data = TeamKitSelectionSerializer(kit_sel).data if kit_sel else None

        own_order = None
        if kit_sel:
            try:
                order = KitOrder.objects.get(team=team, user=request.user)
                own_order = KitOrderSerializer(order).data
            except KitOrder.DoesNotExist:
                pass

        return {
            "kit": kit_data,
            "my_order": own_order,
            "is_captain": request.user.is_captain,
            "team_name": team.name,
            "max_players": team.max_players,
        }

    def get(self, request):
        team = _get_approved_team(request.user)
        if team is None:
            return Response(
                {"detail": "You are not attached to any team."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self._get_kit_data(request, team))

    def patch(self, request):
        if not request.user.is_captain:
            return Response(
                {"detail": "Only the team captain can select a kit."},
                status=status.HTTP_403_FORBIDDEN,
            )

        team = getattr(request.user, "captained_team", None)
        if team is None:
            return Response(
                {"detail": "You do not have a team yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = KitSelectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kit_slug = serializer.validated_data["kit_slug"]

        kit_sel, _ = TeamKitSelection.objects.get_or_create(team=team, defaults={"kit_slug": kit_slug})

        if kit_sel.is_locked:
            return Response(
                {"detail": "Kit selection is locked and cannot be changed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kit_sel.kit_slug = kit_slug
        kit_sel.save(update_fields=["kit_slug", "updated_at"])

        logger.info("Captain %s selected kit %s for team %s", request.user.id, kit_slug, team.id)
        return Response(self._get_kit_data(request, team))


# ---------------------------------------------------------------------------
# POST /kits/my/lock/   — captain locks the kit selection
# ---------------------------------------------------------------------------

class LockKitView(APIView):
    """
    Captain finalises (locks) the kit selection.
    Once locked, the kit slug cannot be changed.
    Sends an email notification to all admin users.
    """

    permission_classes = [IsCaptain]

    def post(self, request):
        team = getattr(request.user, "captained_team", None)
        if team is None:
            return Response(
                {"detail": "You do not have a team yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        kit_sel = getattr(team, "kit_selection", None)
        if kit_sel is None:
            return Response(
                {"detail": "Please select a kit before locking."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if kit_sel.is_locked:
            return Response(
                {"detail": "Kit is already locked."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kit_sel.is_locked = True
        kit_sel.locked_at = timezone.now()
        kit_sel.save(update_fields=["is_locked", "locked_at", "updated_at"])

        send_kit_locked_email(kit_sel)

        logger.info("Captain %s locked kit %s for team %s", request.user.id, kit_sel.kit_slug, team.id)
        return Response(TeamKitSelectionSerializer(kit_sel).data)


# ---------------------------------------------------------------------------
# GET   /kits/my/order/   — any team member: see own order
# POST  /kits/my/order/   — submit order (first time)
# PATCH /kits/my/order/   — update order
# ---------------------------------------------------------------------------

class MyKitOrderView(APIView):
    """
    GET   — Returns caller's existing kit order (or null).
    POST  — Submit size order (only after captain has locked the kit).
    PATCH — Update an already-submitted order.
    """

    permission_classes = [IsAuthenticated]

    def _get_team(self, user) -> Team | None:
        return _get_approved_team(user)

    def _get_locked_kit(self, team: Team) -> TeamKitSelection | None:
        kit_sel = getattr(team, "kit_selection", None)
        if kit_sel and kit_sel.is_locked:
            return kit_sel
        return None

    def get(self, request):
        team = self._get_team(request.user)
        if team is None:
            return Response({"detail": "You are not attached to any team."}, status=status.HTTP_404_NOT_FOUND)

        try:
            order = KitOrder.objects.get(team=team, user=request.user)
            return Response(KitOrderSerializer(order).data)
        except KitOrder.DoesNotExist:
            return Response(None)

    def post(self, request):
        team = self._get_team(request.user)
        if team is None:
            return Response({"detail": "You are not attached to any team."}, status=status.HTTP_404_NOT_FOUND)

        kit_sel = self._get_locked_kit(team)
        if kit_sel is None:
            return Response(
                {"detail": "Kit has not been locked yet. Wait for the captain to finalise the kit selection."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if KitOrder.objects.filter(team=team, user=request.user).exists():
            return Response(
                {"detail": "You have already submitted a kit order. Use PATCH to update it."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = KitOrderSubmitSerializer(
            data=request.data,
            context={"team": team, "user": request.user},
        )
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        order = KitOrder.objects.create(
            team=team,
            user=request.user,
            jersey_size=d["jersey_size"],
            shorts_size=d["shorts_size"],
            socks_size=d["socks_size"],
            name_on_kit=d.get("name_on_kit", ""),
            number_on_kit=d.get("number_on_kit"),
        )

        logger.info("Kit order submitted by user %s for team %s", request.user.id, team.id)
        return Response(KitOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        team = self._get_team(request.user)
        if team is None:
            return Response({"detail": "You are not attached to any team."}, status=status.HTTP_404_NOT_FOUND)

        try:
            order = KitOrder.objects.get(team=team, user=request.user)
        except KitOrder.DoesNotExist:
            return Response(
                {"detail": "No existing order found. Use POST to submit your order first."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = KitOrderSubmitSerializer(
            data=request.data,
            context={"team": team, "user": request.user},
        )
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        order.jersey_size   = d["jersey_size"]
        order.shorts_size   = d["shorts_size"]
        order.socks_size    = d["socks_size"]
        order.name_on_kit   = d.get("name_on_kit", "")
        order.number_on_kit = d.get("number_on_kit")
        order.save(update_fields=["jersey_size", "shorts_size", "socks_size", "name_on_kit", "number_on_kit", "updated_at"])

        logger.info("Kit order updated by user %s for team %s", request.user.id, team.id)
        return Response(KitOrderSerializer(order).data)


# ---------------------------------------------------------------------------
# GET /admin/kits/         — admin: all teams with kit selection + orders
# GET /admin/kits/export/  — admin: CSV download of all kit orders
# ---------------------------------------------------------------------------

class AdminKitListView(APIView):
    """Admin view of all team kit selections with all player orders nested."""

    permission_classes = [IsAdmin]

    def get(self, request):
        selections = (
            TeamKitSelection.objects
            .select_related("team__captain")
            .prefetch_related("team__kit_orders__user")
            .order_by("team__name")
        )
        return Response(AdminTeamKitSerializer(selections, many=True).data)


class AdminKitExportView(APIView):
    """CSV export of all kit orders across all teams."""

    permission_classes = [IsAdmin]

    def get(self, request):
        orders = (
            KitOrder.objects
            .select_related("team", "user")
            .order_by("team__name", "number_on_kit", "user__email")
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="kit_orders.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Team", "Kit", "Name", "Email",
            "Jersey Size", "Shorts Size", "Socks Size",
            "Name on Kit", "Number",
        ])

        for o in orders:
            kit_slug = ""
            try:
                kit_slug = o.team.kit_selection.kit_slug
            except TeamKitSelection.DoesNotExist:
                pass

            writer.writerow([
                o.team.name,
                kit_slug,
                o.user.name or "",
                o.user.email,
                o.jersey_size,
                o.shorts_size,
                o.socks_size,
                o.name_on_kit,
                o.number_on_kit if o.number_on_kit is not None else "",
            ])

        return response
