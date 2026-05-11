from rest_framework import serializers

from apps.users.serializers import UserSerializer

from .models import Team, TeamInvite, TeamMembership


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

class TeamSerializer(serializers.ModelSerializer):
    """Full read representation — includes live roster counts."""

    captain      = UserSerializer(read_only=True)
    playerCount    = serializers.SerializerMethodField()
    pendingCount   = serializers.SerializerMethodField()
    remainingSlots = serializers.SerializerMethodField()

    class Meta:
        model  = Team
        fields = [
            "id", "name", "slug", "captain", "description",
            "logo_url", "max_players", "status",
            "playerCount", "pendingCount", "remainingSlots",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_playerCount(self, obj: Team) -> int:
        return obj.memberships.filter(status=TeamMembership.Status.APPROVED).count()

    def get_pendingCount(self, obj: Team) -> int:
        # Only count committed-but-unapproved members (joined_at set), not bare invites
        return obj.memberships.filter(
            status=TeamMembership.Status.PENDING,
            joined_at__isnull=False,
        ).count()

    def get_remainingSlots(self, obj: Team) -> int:
        approved = obj.memberships.filter(status=TeamMembership.Status.APPROVED).count()
        return max(0, obj.max_players - approved)


class TeamCreateSerializer(serializers.Serializer):
    """Input for POST /teams (captain-only endpoint)."""

    name        = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    logo_url    = serializers.URLField(required=False, allow_null=True)
    max_players = serializers.IntegerField(min_value=8, max_value=11, default=11)

    def validate_name(self, value: str) -> str:
        if Team.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError(f"A team named '{value}' already exists.")
        return value


# ---------------------------------------------------------------------------
# TeamMembership
# ---------------------------------------------------------------------------

class TeamMemberSerializer(serializers.ModelSerializer):
    """
    Roster member — flattened user fields for frontend consumption.
    Used in captain's roster view and admin team overview.

    inviteStatus: the related TeamInvite's status (null for link-based joins).
    membershipBucket:
        'invited'        — captain sent invite, player has not responded yet
        'pending_admin'  — player committed, awaiting admin approval
        'approved'       — admin approved; player is on the official roster
    """

    userId         = serializers.UUIDField(source="user.id", read_only=True)
    name           = serializers.CharField(source="user.name", read_only=True)
    email          = serializers.EmailField(source="user.email", read_only=True)
    division       = serializers.CharField(
        source="user.profile.preferred_division", read_only=True, default=""
    )
    instagram      = serializers.CharField(
        source="user.profile.instagram", read_only=True, default=""
    )
    joinedAt       = serializers.DateTimeField(source="joined_at", read_only=True)
    inviteStatus   = serializers.SerializerMethodField()
    membershipBucket = serializers.SerializerMethodField()

    class Meta:
        model  = TeamMembership
        fields = [
            "id", "userId", "name", "email",
            "division", "instagram",
            "status", "membershipBucket",
            "inviteStatus", "joinedAt",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_inviteStatus(self, obj: TeamMembership) -> str | None:
        if obj.invite is None:
            return None
        return obj.invite.status

    def get_membershipBucket(self, obj: TeamMembership) -> str:
        if obj.status == TeamMembership.Status.APPROVED:
            return "approved"
        if obj.joined_at is not None:
            return "pending_admin"
        return "invited"


# ---------------------------------------------------------------------------
# TeamInvite
# ---------------------------------------------------------------------------

class TeamInviteSerializer(serializers.ModelSerializer):
    """
    Invite representation returned to the captain.

    inviteUrl is the ready-to-share URL:
      - link   invite → {FRONTEND_BASE_URL}/register?invite={token}
      - direct invite → {FRONTEND_BASE_URL}/join/{token}
    """

    invitedUser  = serializers.SerializerMethodField()
    inviteType   = serializers.CharField(source="invite_type", read_only=True)
    expiresAt    = serializers.DateTimeField(source="expires_at", read_only=True)
    createdAt    = serializers.DateTimeField(source="created_at", read_only=True)
    isExpired    = serializers.SerializerMethodField()
    inviteUrl    = serializers.SerializerMethodField()

    class Meta:
        model  = TeamInvite
        fields = [
            "id", "token", "inviteType",
            "invitedUser", "status",
            "inviteUrl",
            "expiresAt", "createdAt", "isExpired",
        ]
        read_only_fields = fields

    def get_invitedUser(self, obj: TeamInvite) -> dict | None:
        if obj.invited_user is None:
            return None
        return {
            "id":    str(obj.invited_user.id),
            "name":  obj.invited_user.name or "",
            "email": obj.invited_user.email,
        }

    def get_isExpired(self, obj: TeamInvite) -> bool:
        return obj.is_expired()

    def get_inviteUrl(self, obj: TeamInvite) -> str:
        from django.conf import settings
        base = getattr(settings, "FRONTEND_BASE_URL", "https://tekkyfutbol.net").rstrip("/")
        if obj.invite_type == TeamInvite.InviteType.LINK:
            return f"{base}/register?invite={obj.token}"
        return f"{base}/join/{obj.token}"


class DirectInviteCreateSerializer(serializers.Serializer):
    """Input for POST /teams/my/invites/direct/ — captain invites a player."""
    playerId = serializers.UUIDField()


class InviteActionSerializer(serializers.Serializer):
    """Input for POST /join/:token/ — player accepts or rejects."""
    action = serializers.ChoiceField(choices=["accept", "reject"])


class MembershipActionSerializer(serializers.Serializer):
    """Input for POST /admin/memberships/<id>/ — admin approves or rejects."""
    action      = serializers.ChoiceField(choices=["approve", "reject"])
    admin_notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class AdminMembershipSerializer(serializers.ModelSerializer):
    """
    Full membership record for the admin dashboard.

    Includes team context, player details, and the invite chain so the admin
    can see exactly how the player arrived (direct invite vs. link).
    """

    userId       = serializers.UUIDField(source="user.id",    read_only=True)
    playerName   = serializers.CharField(source="user.name",  read_only=True)
    playerEmail  = serializers.EmailField(source="user.email",read_only=True)
    teamId       = serializers.UUIDField(source="team.id",    read_only=True)
    teamName     = serializers.CharField(source="team.name",  read_only=True)
    captainEmail = serializers.EmailField(source="team.captain.email", read_only=True)
    joinedAt     = serializers.DateTimeField(source="joined_at",       read_only=True)
    createdAt    = serializers.DateTimeField(source="created_at",      read_only=True)
    inviteType   = serializers.SerializerMethodField()
    inviteStatus = serializers.SerializerMethodField()
    membershipBucket = serializers.SerializerMethodField()

    class Meta:
        model  = TeamMembership
        fields = [
            "id", "status", "membershipBucket",
            "userId", "playerName", "playerEmail",
            "teamId", "teamName", "captainEmail",
            "inviteType", "inviteStatus",
            "joinedAt", "createdAt",
        ]
        read_only_fields = fields

    def get_inviteType(self, obj: TeamMembership) -> str | None:
        return obj.invite.invite_type if obj.invite else None

    def get_inviteStatus(self, obj: TeamMembership) -> str | None:
        return obj.invite.status if obj.invite else None

    def get_membershipBucket(self, obj: TeamMembership) -> str:
        if obj.status == TeamMembership.Status.APPROVED:
            return "approved"
        if obj.joined_at is not None:
            return "pending_admin"
        return "invited"


class LinkInviteRegisterSerializer(serializers.Serializer):
    """
    Input for POST /teams/join-link/<token>/register/

    Non-registered user signs up via a captain's shareable link invite.
    Mirrors the standard RegisterSerializer but role is always 'player'
    (the only role allowed to join a team via link invite).
    """
    email              = serializers.EmailField()
    password           = serializers.CharField(write_only=True, min_length=8)
    password2          = serializers.CharField(write_only=True, min_length=8)
    name               = serializers.CharField(required=False, allow_blank=True, max_length=100)
    phone              = serializers.CharField(required=False, allow_blank=True, max_length=20)
    gender             = serializers.CharField(required=False, allow_blank=True, max_length=10)
    preferred_division = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def validate_email(self, value: str) -> str:
        from apps.users.models import User as _User
        if _User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        return attrs


# ---------------------------------------------------------------------------
# Public join-page representation
# ---------------------------------------------------------------------------

class JoinPageTeamSerializer(serializers.ModelSerializer):
    """
    Minimal team info shown on the public /join/:token page.
    No sensitive data — visible without authentication.
    """

    captainName  = serializers.CharField(source="captain.name", read_only=True)
    playerCount  = serializers.SerializerMethodField()

    class Meta:
        model  = Team
        fields = [
            "id", "name", "logo_url", "description",
            "captainName", "max_players", "playerCount", "status",
        ]
        read_only_fields = fields

    def get_playerCount(self, obj: Team) -> int:
        return obj.memberships.filter(status=TeamMembership.Status.APPROVED).count()


# ---------------------------------------------------------------------------
# Free-agent pool
# ---------------------------------------------------------------------------

class FreeAgentSerializer(serializers.ModelSerializer):
    """
    Representation of an admin-approved free agent for the captain's pool.
    Source model is PlayerProfile — queried directly, not via FreeAgent.

    Fields:
        userId      — UUID of the User (used as playerId in invite payload)
        name        — display name
        email       — contact email
        division    — preferred division (north / south)
        instagram   — optional social handle
        memberSince — when they joined the platform (for captain context)
    """

    userId      = serializers.UUIDField(source="user.id",         read_only=True)
    name        = serializers.CharField(source="user.name",       read_only=True)
    email       = serializers.EmailField(source="user.email",     read_only=True)
    division    = serializers.CharField(source="preferred_division", read_only=True, default="")
    instagram   = serializers.CharField(read_only=True, default="")
    memberSince = serializers.DateTimeField(source="user.created_at", read_only=True)

    class Meta:
        from apps.users.models import PlayerProfile
        model  = PlayerProfile
        fields = ["userId", "name", "email", "division", "instagram", "memberSince"]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Player — own team + membership view
# ---------------------------------------------------------------------------

class PlayerMembershipSerializer(serializers.ModelSerializer):
    """
    A player's own membership record: their status on the team.
    Returned by GET /teams/my-membership/.
    """
    teamId         = serializers.UUIDField(source="team.id",       read_only=True)
    teamName       = serializers.CharField(source="team.name",     read_only=True)
    teamLogoUrl    = serializers.URLField(source="team.logo_url",  read_only=True, allow_null=True)
    teamStatus     = serializers.CharField(source="team.status",   read_only=True)
    maxPlayers     = serializers.IntegerField(source="team.max_players", read_only=True)
    joinedAt       = serializers.DateTimeField(source="joined_at", read_only=True)
    membershipBucket = serializers.SerializerMethodField()

    class Meta:
        model  = TeamMembership
        fields = [
            "id", "status", "membershipBucket",
            "teamId", "teamName", "teamLogoUrl", "teamStatus", "maxPlayers",
            "joinedAt",
        ]
        read_only_fields = fields

    def get_membershipBucket(self, obj: TeamMembership) -> str:
        if obj.status == TeamMembership.Status.APPROVED:
            return "approved"
        if obj.joined_at is not None:
            return "pending_admin"
        return "invited"


# ---------------------------------------------------------------------------
# Admin — team list
# ---------------------------------------------------------------------------

class AdminTeamSerializer(serializers.ModelSerializer):
    """
    Team row for the admin teams table.
    Shows roster counts and status so admin can monitor team formation.
    """
    captainName    = serializers.CharField(source="captain.name",  read_only=True)
    captainEmail   = serializers.EmailField(source="captain.email",read_only=True)
    playerCount    = serializers.SerializerMethodField()
    pendingCount   = serializers.SerializerMethodField()
    remainingSlots = serializers.SerializerMethodField()

    class Meta:
        model  = Team
        fields = [
            "id", "name", "slug", "status",
            "captainName", "captainEmail",
            "max_players", "playerCount", "pendingCount", "remainingSlots",
            "created_at",
        ]
        read_only_fields = fields

    def get_playerCount(self, obj: Team) -> int:
        return obj.memberships.filter(status=TeamMembership.Status.APPROVED).count()

    def get_pendingCount(self, obj: Team) -> int:
        return obj.memberships.filter(
            status=TeamMembership.Status.PENDING,
            joined_at__isnull=False,
        ).count()

    def get_remainingSlots(self, obj: Team) -> int:
        approved = obj.memberships.filter(status=TeamMembership.Status.APPROVED).count()
        return max(0, obj.max_players - approved)
