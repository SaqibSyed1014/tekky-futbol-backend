import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.core.exceptions import InviteInvalidError
from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import IsAdmin, IsCaptain, IsPlayer
from rest_framework.permissions import IsAuthenticated
from apps.users.models import PlayerProfile, User

from .email_service import (
    send_direct_invite_email,
    send_invite_accepted_email,
    send_invite_rejected_email,
)
from .models import Team, TeamInvite, TeamMembership
from .serializers import (
    AdminMembershipSerializer,
    AdminTeamSerializer,
    DirectInviteCreateSerializer,
    FreeAgentSerializer,
    InviteActionSerializer,
    JoinPageTeamSerializer,
    LinkInviteRegisterSerializer,
    MembershipActionSerializer,
    PlayerMembershipSerializer,
    TeamInviteSerializer,
    TeamMemberSerializer,
    TeamSerializer,
)
from .services import InviteService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Captain — My Team
# ---------------------------------------------------------------------------

class MyTeamView(APIView):
    """
    GET /teams/my/
    Returns the captain's own team with roster counts and status.
    """
    permission_classes = [IsCaptain]

    def get(self, request):
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            return Response(
                {"error": {"status_code": 404, "detail": "You do not have a team yet."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(TeamSerializer(team).data)


# ---------------------------------------------------------------------------
# Captain — Roster
# ---------------------------------------------------------------------------

class MyRosterView(APIView):
    """
    GET /teams/my/roster/

    Returns all memberships for the captain's team, split into three buckets:

        approved      — admin-approved roster members (count toward max_players)
        pending_admin — player committed (accepted invite or signed up via link),
                        awaiting admin approval; joined_at IS NOT NULL
        invited       — captain sent a direct invite but player has not yet
                        responded; joined_at IS NULL

    This gives the captain a complete, real-time view of their team pipeline.
    """
    permission_classes = [IsCaptain]

    def get(self, request):
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            empty = {"count": 0, "results": []}
            return Response({"approved": empty, "pending_admin": empty, "invited": empty})

        base_qs = (
            TeamMembership.objects
            .filter(team=team)
            .select_related("user", "user__profile", "invite")
            .order_by("joined_at", "created_at")
        )

        approved     = base_qs.filter(status=TeamMembership.Status.APPROVED)
        pending_admin = base_qs.filter(
            status=TeamMembership.Status.PENDING,
            joined_at__isnull=False,
        )
        invited      = base_qs.filter(
            status=TeamMembership.Status.PENDING,
            joined_at__isnull=True,
        )

        def _bucket(qs):
            data = TeamMemberSerializer(qs, many=True).data
            return {"count": len(data), "results": data}

        return Response({
            "approved":      _bucket(approved),
            "pending_admin": _bucket(pending_admin),
            "invited":       _bucket(invited),
            # Convenience totals
            "rosterCount":  approved.count(),
            "maxPlayers":   team.max_players,
            "teamStatus":   team.status,
        })


class RemovePlayerView(APIView):
    """
    DELETE /teams/my/roster/<user_id>/
    Captain removes a player from the team.
    """
    permission_classes = [IsCaptain]

    def delete(self, request, user_id):
        try:
            player = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": {"status_code": 404, "detail": "Player not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        from apps.core.exceptions import DomainError
        try:
            team = request.user.captained_team
            from .services import TeamService
            TeamService.remove_player(captain=request.user, player=player)
        except DomainError as exc:
            return Response(
                {"error": {"status_code": 400, "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Captain — Direct Invites
# ---------------------------------------------------------------------------

class DirectInviteView(APIView):
    """
    POST /teams/my/invites/direct/

    Captain sends a direct invite to a registered free-agent player.

    Request body:
        { "playerId": "<uuid>" }

    Validations (in order):
        1. playerId resolves to an active player
        2. Player has an admin-approved free_agent application
        3. Player is not already on a team
        4. Player does not already have a pending invite to this team
        5. Team is not at capacity

    Response: the created TeamInvite (includes inviteUrl for debugging/audit).
    Side-effect: invite email is dispatched to the player via transaction.on_commit.
    """
    permission_classes = [IsCaptain]

    def post(self, request):
        serializer = DirectInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        player_id = serializer.validated_data["playerId"]

        # 1. Player must exist and be active
        try:
            player = User.objects.get(id=player_id, role=User.Role.PLAYER, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"error": {"status_code": 404, "detail": "Player not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Player must be admin-approved (approved free_agent application)
        is_approved = Application.objects.filter(
            applicant=player,
            type=Application.Type.FREE_AGENT,
            status=Application.Status.APPROVED,
        ).exists()
        if not is_approved:
            return Response(
                {
                    "error": {
                        "status_code": 403,
                        "detail": "This player has not been approved by admin yet.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3–5 handled by InviteService (team full, already on team, already invited)
        from apps.core.exceptions import DomainError
        try:
            team   = request.user.captained_team
            invite = InviteService.create_direct_invite(
                captain=request.user,
                player=player,
                team=team,
            )
        except DomainError as exc:
            return Response(
                {"error": {"status_code": 409, "detail": str(exc)}},
                status=status.HTTP_409_CONFLICT,
            )

        # Dispatch invite email (fires after transaction commits)
        send_direct_invite_email(invite)

        return Response(TeamInviteSerializer(invite).data, status=status.HTTP_201_CREATED)


class InviteListView(APIView):
    """
    GET /teams/my/invites/
    Captain sees all pending invites (direct + link) for their team.
    """
    permission_classes = [IsCaptain]

    def get(self, request):
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            return Response({"results": [], "count": 0})

        invites = (
            TeamInvite.objects
            .filter(team=team, status=TeamInvite.Status.PENDING)
            .select_related("invited_user")
            .order_by("-created_at")
        )
        return Response({
            "count":   invites.count(),
            "results": TeamInviteSerializer(invites, many=True).data,
        })


class RevokeInviteView(APIView):
    """
    DELETE /teams/my/invites/<invite_id>/
    Captain revokes a pending invite.
    """
    permission_classes = [IsCaptain]

    def delete(self, request, invite_id):
        from apps.core.exceptions import DomainError
        try:
            InviteService.revoke_invite(invite_id=invite_id, captain=request.user)
        except DomainError as exc:
            return Response(
                {"error": {"status_code": 400, "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Captain — Link Invite
# ---------------------------------------------------------------------------

class LinkInviteView(APIView):
    """
    GET  /teams/my/invites/link/  — get (or create) the active link invite
    POST /teams/my/invites/link/  — force-regenerate the link invite
    """
    permission_classes = [IsCaptain]

    def get(self, request):
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            return Response(
                {"error": {"status_code": 404, "detail": "You do not have a team yet."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        invite = InviteService.get_or_create_link_invite(captain=request.user, team=team)
        return Response(TeamInviteSerializer(invite).data)

    def post(self, request):
        """Force-regenerate a new link invite (invalidates the old one)."""
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            return Response(
                {"error": {"status_code": 404, "detail": "You do not have a team yet."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        invite = InviteService.regenerate_link_invite(captain=request.user, team=team)
        return Response(TeamInviteSerializer(invite).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Captain — Free Agent Pool
# ---------------------------------------------------------------------------

class FreeAgentPoolView(APIView):
    """
    GET /teams/free-agents/

    Returns paginated list of players who are:
      1. Approved by admin (Application type=free_agent, status=approved)
      2. Not currently on any team (PlayerProfile.team is null)
      3. Not already sent a pending direct invite from this captain's team

    Query params:
      search   — filters by name or email (case-insensitive contains)
      division — filters by preferred_division (north / south)
      page     — page number (default 1)
      page_size — results per page (default 20, max 100)
    """
    permission_classes = [IsCaptain]

    def get(self, request):
        try:
            team = request.user.captained_team
        except Team.DoesNotExist:
            team = None

        # IDs of players who already have a pending direct invite to this team
        already_invited_ids = set()
        if team:
            already_invited_ids = set(
                TeamInvite.objects
                .filter(
                    team=team,
                    status=TeamInvite.Status.PENDING,
                    invite_type=TeamInvite.InviteType.DIRECT,
                )
                .values_list("invited_user_id", flat=True)
            )

        # IDs of players approved by admin as free agents
        approved_player_ids = (
            Application.objects
            .filter(
                type=Application.Type.FREE_AGENT,
                status=Application.Status.APPROVED,
            )
            .values_list("applicant_id", flat=True)
        )

        # Base queryset: approved, teamless, not already invited
        profiles = (
            PlayerProfile.objects
            .filter(
                user_id__in=approved_player_ids,
                team__isnull=True,
                user__is_active=True,
            )
            .exclude(user_id__in=already_invited_ids)
            .select_related("user")
            .distinct()
        )

        # ── Filtering ─────────────────────────────────────────────────
        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            profiles = profiles.filter(
                Q(user__name__icontains=search) | Q(user__email__icontains=search)
            )

        division = request.query_params.get("division", "").strip()
        if division:
            profiles = profiles.filter(preferred_division=division)

        # ── Ordering ──────────────────────────────────────────────────
        profiles = profiles.order_by("user__name", "user__email")

        # ── Pagination ────────────────────────────────────────────────
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(profiles, request)
        return paginator.get_paginated_response(
            FreeAgentSerializer(page, many=True).data
        )


# ---------------------------------------------------------------------------
# Public — Validate link invite (before registration)
# ---------------------------------------------------------------------------

class ValidateLinkInviteView(APIView):
    """
    GET /teams/join-link/<token>/validate/

    Public endpoint — no authentication required.
    Called by the frontend when a non-registered user lands on the
    registration page with an ?invite=TOKEN param.

    Returns team details and confirms the invite is usable before
    the user fills in the registration form.

    Validation order:
        1. Token exists and is a link-type invite
        2. Status is pending (not revoked / expired)
        3. Not past expiry date
        4. Team is not at max capacity
    """
    permission_classes = []

    def get(self, request, token):
        from apps.core.exceptions import DomainError
        try:
            invite = InviteService.validate_link_invite(str(token))
        except DomainError as exc:
            return Response(
                {
                    "valid": False,
                    "error": str(exc),
                },
                status=status.HTTP_200_OK,   # always 200 — let frontend decide UI
            )

        return Response({
            "valid":     True,
            "expiresAt": invite.expires_at,
            "team":      JoinPageTeamSerializer(invite.team).data,
        })


# ---------------------------------------------------------------------------
# Public — Join Page (registered player direct invite)
# ---------------------------------------------------------------------------

class JoinPageView(APIView):
    """
    GET  /teams/join/<token>/  — public; validates token + returns team details
    POST /teams/join/<token>/  — player accepts or rejects (JWT required)

    GET validation order:
        1. Token exists (direct type)
        2. Status is pending
        3. Not expired
        4. Team is not full
    """
    permission_classes = []  # public GET; POST validates token ownership

    def get(self, request, token):
        from apps.core.exceptions import DomainError
        try:
            invite = InviteService.validate_direct_invite(str(token))
            return Response({
                "valid":        True,
                "inviteStatus": invite.status,
                "isExpired":    False,
                "expiresAt":    invite.expires_at,
                "team":         JoinPageTeamSerializer(invite.team).data,
            })
        except DomainError as exc:
            # Still return team info if the invite exists but is just expired/full,
            # so the page can show a meaningful message rather than a blank screen.
            try:
                invite = TeamInvite.objects.select_related("team", "team__captain").get(
                    token=token,
                    invite_type=TeamInvite.InviteType.DIRECT,
                )
                return Response({
                    "valid":        False,
                    "inviteStatus": invite.status,
                    "isExpired":    invite.is_expired(),
                    "expiresAt":    invite.expires_at,
                    "team":         JoinPageTeamSerializer(invite.team).data,
                    "error":        str(exc),
                })
            except TeamInvite.DoesNotExist:
                return Response(
                    {"valid": False, "error": str(exc)},
                    status=status.HTTP_404_NOT_FOUND,
                )

    def post(self, request, token):
        """Player accepts or rejects. Player must supply their JWT."""
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"error": {"status_code": 401, "detail": "Authentication required."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = InviteActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        from apps.core.exceptions import DomainError
        try:
            if action == "accept":
                InviteService.accept_direct_invite(token=str(token), player=request.user)
                invite = TeamInvite.objects.select_related("team", "invited_by", "invited_user").get(token=token)
                send_invite_accepted_email(invite)
                return Response({"detail": f"You have joined {invite.team.name}!"})
            else:
                invite = InviteService.reject_direct_invite(token=str(token), player=request.user)
                invite.refresh_from_db()
                invite = TeamInvite.objects.select_related("team", "invited_by", "invited_user").get(token=token)
                send_invite_rejected_email(invite)
                return Response({"detail": "Invite declined."})
        except DomainError as exc:
            return Response(
                {"error": {"status_code": 400, "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )


# ---------------------------------------------------------------------------
# Public — Join via Link (called after non-registered user signs up)
# ---------------------------------------------------------------------------

class JoinViaLinkView(APIView):
    """
    POST /teams/join-link/<token>/
    Called immediately after a non-registered user completes registration
    via a shared link invite.

    The frontend passes the invite token (stored from URL params during
    registration) after the user's account is created and they are logged in.

    Expects: JWT in Authorization header (user just registered + got token).
    """
    permission_classes = [IsPlayer]

    def post(self, request, token):
        from apps.core.exceptions import DomainError
        try:
            membership = InviteService.join_via_link_token(
                token=str(token),
                user=request.user,
            )
        except DomainError as exc:
            return Response(
                {"error": {"status_code": 400, "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            "detail":   f"You have been added to {membership.team.name}!",
            "teamName": membership.team.name,
            "teamLogo": membership.team.logo_url or "",
            "status":   membership.team.status,
        }, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Player — Own Membership + Team Info
# ---------------------------------------------------------------------------

class PlayerMembershipView(APIView):
    """
    GET /teams/my-membership/

    Returns the authenticated player's active team membership along with
    basic team info and the list of approved teammates.

    Used by the player dashboard to show:
        - team name / logo / status
        - the player's own membership status (pending_admin / approved)
        - teammates (approved roster members, excluding self)

    Returns 404 when the player has no committed membership
    (invite not yet accepted / not on any team).

    Permission: players only (IsCaptain excluded — captains use /teams/my/).
    """
    permission_classes = [IsPlayer]

    def get(self, request):
        from django.db.models import Q
        # Find committed membership: approved OR pending-with-joined_at
        membership = (
            TeamMembership.objects
            .filter(
                Q(user=request.user, status=TeamMembership.Status.APPROVED) |
                Q(user=request.user, status=TeamMembership.Status.PENDING, joined_at__isnull=False)
            )
            .select_related("team", "team__captain", "invite")
            .first()
        )

        if membership is None:
            return Response(
                {"error": {"status_code": 404, "detail": "You are not on a team yet."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Approved teammates (excluding self)
        teammates_qs = (
            TeamMembership.objects
            .filter(team=membership.team, status=TeamMembership.Status.APPROVED)
            .exclude(user=request.user)
            .select_related("user", "user__profile")
            .order_by("joined_at")
        )

        return Response({
            "membership": PlayerMembershipSerializer(membership).data,
            "teammates":  TeamMemberSerializer(teammates_qs, many=True).data,
        })


# ---------------------------------------------------------------------------
# Admin — Pending Membership Queue
# ---------------------------------------------------------------------------

class AdminMembershipListView(APIView):
    """
    GET /admin/memberships/

    Returns all memberships awaiting admin approval (status=pending,
    joined_at IS NOT NULL — player has committed but admin hasn't acted yet).

    Optional query params:
        team   — UUID; filter by team
        status — 'pending' (default) | 'approved' | 'all'
        page / page_size — pagination (uses StandardResultsPagination)

    Permission: admin only.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        from apps.core.permissions import IsAdmin as _IsAdmin

        status_param = request.query_params.get("status", "pending").strip()
        team_id      = request.query_params.get("team", "").strip()

        qs = (
            TeamMembership.objects
            .select_related("user", "team", "team__captain", "invite")
            .order_by("-joined_at", "-created_at")
        )

        if status_param == "pending":
            qs = qs.filter(
                status=TeamMembership.Status.PENDING,
                joined_at__isnull=False,
            )
        elif status_param == "approved":
            qs = qs.filter(status=TeamMembership.Status.APPROVED)
        # 'all' → no status filter

        if team_id:
            qs = qs.filter(team__id=team_id)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            AdminMembershipSerializer(page, many=True).data
        )


class AdminMembershipActionView(APIView):
    """
    POST /admin/memberships/<membership_id>/

    Admin approves or rejects a pending membership.

    Request body:
        { "action": "approve" | "reject", "admin_notes": "<optional>" }

    approve:
        - Flips TeamMembership → approved
        - Syncs PlayerProfile.team + status=ACTIVE
        - Rechecks team status (may flip forming → official)
        - Sends approval email to player

    reject:
        - Deletes the TeamMembership row
        - Player remains without a team; their Application status is unchanged
        - Sends rejection email to player

    Permission: admin only.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, membership_id):
        serializer = MembershipActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action      = serializer.validated_data["action"]
        admin_notes = serializer.validated_data.get("admin_notes", "")

        from apps.core.exceptions import DomainError
        try:
            if action == "approve":
                membership = InviteService.approve_membership(
                    membership_id=str(membership_id),
                    admin=request.user,
                )
                from .email_service import send_membership_approved_email
                send_membership_approved_email(membership)
                return Response(
                    AdminMembershipSerializer(membership).data,
                    status=status.HTTP_200_OK,
                )
            else:  # reject
                # Fetch membership before deletion for email
                try:
                    membership_obj = (
                        TeamMembership.objects
                        .select_related("user", "team", "team__captain", "invite")
                        .get(id=membership_id)
                    )
                except TeamMembership.DoesNotExist:
                    return Response(
                        {"error": {"status_code": 404, "detail": "Membership not found."}},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                from .email_service import send_membership_rejected_email
                send_membership_rejected_email(membership_obj)
                InviteService.reject_membership(
                    membership_id=str(membership_id),
                    admin=request.user,
                )
                return Response(status=status.HTTP_204_NO_CONTENT)

        except DomainError as exc:
            return Response(
                {"error": {"status_code": 400, "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )


# ---------------------------------------------------------------------------
# Admin — Team List
# ---------------------------------------------------------------------------

class AdminTeamListView(APIView):
    """
    GET /admin/teams/

    Paginated list of all teams with live roster counts.
    Used by the admin panel to monitor team formation progress.

    Query params:
        status   — 'forming' | 'official' | '' (all)
        search   — partial match on team name
        page / page_size
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = (
            Team.objects
            .select_related("captain")
            .prefetch_related("memberships")
            .order_by("name")
        )

        status_param = request.query_params.get("status", "").strip()
        if status_param in (Team.Status.FORMING, Team.Status.OFFICIAL):
            qs = qs.filter(status=status_param)

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(name__icontains=search)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            AdminTeamSerializer(page, many=True).data
        )


# ---------------------------------------------------------------------------
# Public — Register + Join via Link (one-shot for non-registered users)
# ---------------------------------------------------------------------------

class LinkInviteRegisterView(APIView):
    """
    POST /teams/join-link/<token>/register/

    One-shot endpoint for a non-registered user who clicked a captain's
    shareable invite link.

    The frontend:
        1. Calls GET /teams/join-link/<token>/validate/ to confirm the link
           is valid and show the team details / registration form.
        2. User fills in the form and submits to THIS endpoint.

    This view atomically:
        - Validates the invite token (pending, not expired, team not full)
        - Creates a new User account (role=player)
        - Creates a PlayerProfile (done by UserService.create_user)
        - Creates an approved TeamMembership immediately
        - Returns JWT tokens + user + team info so the frontend can log
          the user in without an extra round trip.

    Permission: public — no authentication required.
    """
    permission_classes = []

    def post(self, request, token):
        serializer = LinkInviteRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from apps.core.exceptions import DomainError
        try:
            user, membership = InviteService.register_and_join(
                token=str(token),
                email=data["email"],
                password=data["password"],
                name=data.get("name", ""),
                phone=data.get("phone", ""),
                gender=data.get("gender", ""),
                preferred_division=data.get("preferred_division", ""),
            )
        except DomainError as exc:
            return Response(
                {"error": {"status_code": 400, "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.users.serializers import UserDetailSerializer

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        logger.info(
            "User %s registered and joined team %s via link invite (token=%s)",
            user.id, membership.team.name, token,
        )

        return Response(
            {
                "token":   access_token,   # frontend alias
                "access":  access_token,
                "refresh": str(refresh),
                "user":    UserDetailSerializer(user).data,
                "team": {
                    "id":       str(membership.team.id),
                    "name":     membership.team.name,
                    "logo_url": membership.team.logo_url or "",
                    "status":   membership.team.status,
                },
                "detail": f"Welcome! You have been added to {membership.team.name}.",
            },
            status=status.HTTP_201_CREATED,
        )
