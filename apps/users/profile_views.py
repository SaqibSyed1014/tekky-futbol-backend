"""
Milestone 8 — Public profile + stats + link management views.

Endpoints defined here:
  GET  /api/v1/profiles/<user_id>/              — public player profile (no auth)
  GET  /api/v1/teams/public/<slug>/             — public team profile (no auth)
  POST /api/v1/users/profile/me/link/           — player submits/clears profile link
  POST /api/v1/users/team/link/                 — captain submits/clears team link
  GET  /api/v1/admin/players/                   — admin: all players with stats + link status
  PATCH /api/v1/admin/players/<user_id>/stats/  — admin: edit player stats
  PATCH /api/v1/admin/players/<user_id>/profile-link/ — admin: approve/reject profile link
  PATCH /api/v1/admin/teams/<team_id>/team-link/ — admin: approve/reject team link
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin
from apps.core.pagination import StandardResultsPagination

from .models import PlayerProfile, User

logger = logging.getLogger(__name__)

FRONTEND_BASE = getattr(settings, "FRONTEND_BASE_URL", "https://tekkyfutbol.net").rstrip("/")


# ---------------------------------------------------------------------------
# Serializers (inline to keep this file self-contained)
# ---------------------------------------------------------------------------

from rest_framework import serializers


class PublicProfileSerializer(serializers.ModelSerializer):
    """Full public-facing player profile."""

    name       = serializers.CharField(source="user.name",  read_only=True)
    email      = serializers.EmailField(source="user.email", read_only=True)
    user_id    = serializers.UUIDField(source="user.id",    read_only=True)
    is_captain = serializers.BooleanField(source="user.is_captain", read_only=True)
    team_name  = serializers.SerializerMethodField()
    team_link  = serializers.SerializerMethodField()
    kit_slug   = serializers.SerializerMethodField()
    profile_link = serializers.SerializerMethodField()  # only if approved

    class Meta:
        model = PlayerProfile
        fields = [
            "user_id", "name", "email", "is_captain",
            "position", "bio", "instagram", "preferred_division",
            "team_name", "team_link", "kit_slug",
            # Stats
            "goals", "assists", "matches_played", "mvps",
            # Upcoming match
            "upcoming_opponent", "upcoming_date", "upcoming_kickoff", "upcoming_location",
            # Team standing
            "team_rank", "team_wins", "team_losses", "team_draws", "team_goal_difference",
            # Approved profile link only
            "profile_link",
        ]
        read_only_fields = fields

    def get_team_name(self, obj):
        return obj.team.name if obj.team else None

    def get_team_link(self, obj):
        if obj.team and obj.team.team_link_status == "approved":
            return obj.team.team_link
        return None

    def get_kit_slug(self, obj):
        if obj.team:
            try:
                sel = obj.team.kit_selection
                if sel.is_locked:
                    return sel.kit_slug
            except Exception:
                pass
        return None

    def get_profile_link(self, obj):
        if obj.profile_link_status == "approved":
            return obj.profile_link
        return None


class AdminPlayerStatsListSerializer(serializers.ModelSerializer):
    """Row in the admin players stats table."""

    user_id      = serializers.UUIDField(source="user.id",    read_only=True)
    name         = serializers.CharField(source="user.name",  read_only=True)
    email        = serializers.EmailField(source="user.email", read_only=True)
    is_captain   = serializers.BooleanField(source="user.is_captain", read_only=True)
    team_name    = serializers.SerializerMethodField()
    public_url   = serializers.SerializerMethodField()

    class Meta:
        model = PlayerProfile
        fields = [
            "user_id", "name", "email", "is_captain",
            "team_name", "status", "is_public", "public_url",
            "profile_link", "profile_link_status",
            "goals", "assists", "matches_played", "mvps",
            "upcoming_opponent", "upcoming_date", "upcoming_kickoff", "upcoming_location",
            "team_rank", "team_wins", "team_losses", "team_draws", "team_goal_difference",
        ]
        read_only_fields = fields

    def get_team_name(self, obj):
        return obj.team.name if obj.team else None

    def get_public_url(self, obj):
        if obj.is_public:
            return f"{FRONTEND_BASE}/profile/{obj.user_id}"
        return None


class AdminStatsUpdateSerializer(serializers.Serializer):
    """Input for PATCH /admin/players/<id>/stats/"""

    goals              = serializers.IntegerField(required=False, min_value=0)
    assists            = serializers.IntegerField(required=False, min_value=0)
    matches_played     = serializers.IntegerField(required=False, min_value=0)
    mvps               = serializers.IntegerField(required=False, min_value=0)
    upcoming_opponent  = serializers.CharField(required=False, allow_blank=True, max_length=100)
    upcoming_date      = serializers.DateField(required=False, allow_null=True)
    upcoming_kickoff   = serializers.CharField(required=False, allow_blank=True, max_length=20)
    upcoming_location  = serializers.CharField(required=False, allow_blank=True, max_length=200)
    team_rank          = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    team_wins          = serializers.IntegerField(required=False, min_value=0)
    team_losses        = serializers.IntegerField(required=False, min_value=0)
    team_draws         = serializers.IntegerField(required=False, min_value=0)
    team_goal_difference = serializers.IntegerField(required=False)


class LinkReviewSerializer(serializers.Serializer):
    """Admin approves or rejects a submitted link."""
    action = serializers.ChoiceField(choices=["approve", "reject"])


class ProfileLinkSubmitSerializer(serializers.Serializer):
    """Player submits or clears their personal profile link."""
    profile_link = serializers.URLField(required=False, allow_blank=True, allow_null=True)


class TeamLinkSubmitSerializer(serializers.Serializer):
    """Captain submits or clears their team link."""
    team_link = serializers.URLField(required=False, allow_blank=True, allow_null=True)


# ---------------------------------------------------------------------------
# Public profile view
# ---------------------------------------------------------------------------

class PublicProfileView(APIView):
    """
    GET /api/v1/profiles/<user_id>/

    Returns a player's public profile. No authentication required.
    Returns 404 if the profile does not exist or is not public yet.
    """
    permission_classes = [AllowAny]

    def get(self, request, user_id):
        try:
            profile = (
                PlayerProfile.objects
                .select_related("user", "team__kit_selection")
                .get(user_id=user_id, is_public=True)
            )
        except PlayerProfile.DoesNotExist:
            return Response(
                {"detail": "Profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(PublicProfileSerializer(profile).data)


# ---------------------------------------------------------------------------
# Player: submit / clear own profile link
# ---------------------------------------------------------------------------

class ProfileLinkView(APIView):
    """
    POST /api/v1/users/profile/me/link/

    Player submits a personal profile link.
    - Providing a URL → status becomes 'pending' (awaiting admin approval).
    - Providing null/blank → clears the link and resets status to 'none'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = getattr(request.user, "profile", None)
        if profile is None:
            return Response(
                {"detail": "No player profile found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProfileLinkSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = serializer.validated_data.get("profile_link") or None

        if link:
            profile.profile_link = link
            profile.profile_link_status = PlayerProfile.LinkStatus.PENDING
        else:
            profile.profile_link = None
            profile.profile_link_status = PlayerProfile.LinkStatus.NONE

        profile.save(update_fields=["profile_link", "profile_link_status", "updated_at"])
        logger.info("User %s submitted profile link (status=pending)", request.user.id)

        return Response({
            "profile_link": profile.profile_link,
            "profile_link_status": profile.profile_link_status,
        })


# ---------------------------------------------------------------------------
# Captain: submit / clear team link
# ---------------------------------------------------------------------------

class TeamLinkView(APIView):
    """
    POST /api/v1/teams/my/link/

    Captain submits an external team link (e.g. Instagram, highlights).
    - Providing a URL → status becomes 'pending'.
    - Providing null/blank → clears the link and resets status to 'none'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_captain:
            return Response(
                {"detail": "Only team captains can submit a team link."},
                status=status.HTTP_403_FORBIDDEN,
            )

        from apps.teams.models import Team
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            return Response(
                {"detail": "You do not have a team yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TeamLinkSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = serializer.validated_data.get("team_link") or None

        if link:
            team.team_link = link
            team.team_link_status = Team.LinkStatus.PENDING
        else:
            team.team_link = None
            team.team_link_status = Team.LinkStatus.NONE

        team.save(update_fields=["team_link", "team_link_status", "updated_at"])
        logger.info("Captain %s submitted team link for team %s", request.user.id, team.id)

        return Response({
            "team_link": team.team_link,
            "team_link_status": team.team_link_status,
        })


# ---------------------------------------------------------------------------
# Admin: player stats list
# ---------------------------------------------------------------------------

class AdminPlayerListView(APIView):
    """
    GET /api/v1/admin/players/

    Paginated list of all players with stats, profile link status, and
    public profile URL. Admin only.

    Query params: search (name/email), is_public (true|false)
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = (
            PlayerProfile.objects
            .select_related("user", "team")
            .filter(user__role="player")
            .order_by("user__name", "user__email")
        )

        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(user__name__icontains=search) | Q(user__email__icontains=search)
            )

        is_public_param = request.query_params.get("is_public", "").lower()
        if is_public_param == "true":
            qs = qs.filter(is_public=True)
        elif is_public_param == "false":
            qs = qs.filter(is_public=False)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminPlayerStatsListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# Admin: edit player stats
# ---------------------------------------------------------------------------

class AdminPlayerStatsUpdateView(APIView):
    """
    PATCH /api/v1/admin/players/<user_id>/stats/

    Admin updates any combination of stat fields for a player.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, user_id):
        try:
            profile = PlayerProfile.objects.select_related("user").get(user_id=user_id)
        except PlayerProfile.DoesNotExist:
            return Response({"detail": "Player not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AdminStatsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        STAT_FIELDS = [
            "goals", "assists", "matches_played", "mvps",
            "upcoming_opponent", "upcoming_date", "upcoming_kickoff", "upcoming_location",
            "team_rank", "team_wins", "team_losses", "team_draws", "team_goal_difference",
        ]
        changed = []
        for field in STAT_FIELDS:
            if field in d:
                setattr(profile, field, d[field])
                changed.append(field)

        if changed:
            profile.save(update_fields=changed + ["updated_at"])
            logger.info("Admin %s updated stats for player %s: %s", request.user.id, user_id, changed)

        return Response(AdminPlayerStatsListSerializer(profile).data)


# ---------------------------------------------------------------------------
# Admin: approve / reject player profile link
# ---------------------------------------------------------------------------

class AdminProfileLinkReviewView(APIView):
    """
    PATCH /api/v1/admin/players/<user_id>/profile-link/

    Admin approves or rejects a player's pending profile link.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, user_id):
        try:
            profile = PlayerProfile.objects.get(user_id=user_id)
        except PlayerProfile.DoesNotExist:
            return Response({"detail": "Player not found."}, status=status.HTTP_404_NOT_FOUND)

        if profile.profile_link_status not in ("pending", "approved", "rejected"):
            return Response(
                {"detail": "No link has been submitted by this player."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = LinkReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        profile.profile_link_status = (
            PlayerProfile.LinkStatus.APPROVED if action == "approve"
            else PlayerProfile.LinkStatus.REJECTED
        )
        profile.save(update_fields=["profile_link_status", "updated_at"])
        logger.info("Admin %s %sd profile link for player %s", request.user.id, action, user_id)

        return Response({
            "profile_link": profile.profile_link,
            "profile_link_status": profile.profile_link_status,
        })


# ---------------------------------------------------------------------------
# Admin: approve / reject team link
# ---------------------------------------------------------------------------

class AdminTeamLinkReviewView(APIView):
    """
    PATCH /api/v1/admin/teams/<team_id>/team-link/

    Admin approves or rejects a captain's pending team link.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, team_id):
        from apps.teams.models import Team
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({"detail": "Team not found."}, status=status.HTTP_404_NOT_FOUND)

        if team.team_link_status not in ("pending", "approved", "rejected"):
            return Response(
                {"detail": "No link has been submitted for this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = LinkReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        team.team_link_status = (
            Team.LinkStatus.APPROVED if action == "approve"
            else Team.LinkStatus.REJECTED
        )
        team.save(update_fields=["team_link_status", "updated_at"])
        logger.info("Admin %s %sd team link for team %s", request.user.id, action, team_id)

        return Response({
            "team_link": team.team_link,
            "team_link_status": team.team_link_status,
        })


# ---------------------------------------------------------------------------
# Public team profile
# ---------------------------------------------------------------------------

class PublicTeamProfileView(APIView):
    """
    GET /api/v1/teams/public/<slug>/

    Returns a team's public profile. No authentication required.
    Includes roster of approved players whose profiles are public,
    the locked kit slug (if selected), and the approved team link.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        from apps.teams.models import Team, TeamMembership
        from apps.kits.models import KitOrder

        try:
            team = (
                Team.objects
                .select_related("captain")
                .get(slug=slug, is_active=True)
            )
        except Team.DoesNotExist:
            return Response({"detail": "Team not found."}, status=status.HTTP_404_NOT_FOUND)

        # Approved public roster members
        memberships = (
            TeamMembership.objects
            .filter(team=team, status=TeamMembership.Status.APPROVED)
            .select_related("user__profile")
        )

        # Kit orders keyed by user_id for jersey number lookup
        kit_orders = {
            str(ko.user_id): ko
            for ko in KitOrder.objects.filter(team=team)
        }

        roster = []
        for m in memberships:
            profile = getattr(m.user, "profile", None)
            if not profile or not profile.is_public:
                continue
            ko = kit_orders.get(str(m.user_id))
            roster.append({
                "user_id":      str(m.user.id),
                "name":         m.user.name or "",
                "position":     profile.position or "",
                "number_on_kit": ko.number_on_kit if ko else None,
            })

        # Kit slug — only if captain has locked
        kit_slug = None
        try:
            sel = team.kit_selection
            if sel.is_locked:
                kit_slug = sel.kit_slug
        except Exception:
            pass

        data = {
            "name":         team.name,
            "slug":         team.slug,
            "description":  team.description or "",
            "logo_url":     team.logo_url,
            "status":       team.status,
            "captain_name":    team.captain.name or team.captain.email,
            "captain_user_id": str(team.captain.id),
            "team_link": team.team_link if team.team_link_status == "approved" else None,
            "kit_slug":  kit_slug,
            "roster":    roster,
        }

        return Response(data)
