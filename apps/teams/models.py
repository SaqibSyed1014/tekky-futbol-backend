import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone


class Team(models.Model):
    """
    A registered football team. Each team has exactly one captain.
    The captain FK is UNIQUE — enforcing the one-captain-one-team constraint
    at the database level.
    """

    class Status(models.TextChoices):
        FORMING  = "forming",  "Forming"
        OFFICIAL = "official", "Official"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=100, unique=True)
    slug       = models.SlugField(max_length=120, unique=True, db_index=True)
    captain    = models.OneToOneField(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="captained_team",
        db_index=True,
    )
    description = models.TextField(null=True, blank=True)
    logo_url    = models.URLField(null=True, blank=True)
    max_players = models.PositiveSmallIntegerField(default=11)
    status      = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.FORMING,
        db_index=True,
    )
    is_active   = models.BooleanField(default=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teams"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"],   name="teams_active_name_idx"),
            models.Index(fields=["status", "is_active"], name="teams_status_active_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(max_players__gte=8) & models.Q(max_players__lte=11),
                name="teams_max_players_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def approved_member_count(self) -> int:
        """Number of approved memberships (excludes the captain)."""
        return self.memberships.filter(status=TeamMembership.Status.APPROVED).count()

    def is_full(self) -> bool:
        return self.approved_member_count() >= self.max_players


# ---------------------------------------------------------------------------
# TeamInvite
# ---------------------------------------------------------------------------

def _default_expiry():
    return timezone.now() + timedelta(days=7)


class TeamInvite(models.Model):
    """
    Represents an invitation for a player to join a team.

    Two invite types:
        direct — captain invites a specific registered player by selecting
                  them from the free-agent pool.  invited_user is populated.
                  A unique invite email is sent; the player accepts/rejects
                  on the /join/:token page.

        link   — captain generates a shareable URL token to paste into
                  WhatsApp, social media, etc.  invited_user is null.
                  Any non-registered user who clicks the link lands on the
                  registration page pre-loaded with the invite token.
                  After signup they are auto-added to the team.
    """

    class InviteType(models.TextChoices):
        DIRECT = "direct", "Direct"
        LINK   = "link",   "Link"

    class Status(models.TextChoices):
        PENDING  = "pending",  "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        EXPIRED  = "expired",  "Expired"
        REVOKED  = "revoked",  "Revoked"

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team         = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        related_name="invites",
    )
    invited_by   = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="sent_invites",
    )
    invited_user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_invites",
    )
    token        = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    invite_type  = models.CharField(max_length=10, choices=InviteType.choices)
    status       = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    expires_at   = models.DateTimeField(default=_default_expiry)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "team_invites"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "status"],        name="teaminvite_team_status_idx"),
            models.Index(fields=["invited_user", "status"],name="teaminvite_user_status_idx"),
        ]
        constraints = [
            # A registered player can only have one pending direct invite per team
            models.UniqueConstraint(
                fields=["team", "invited_user"],
                condition=models.Q(status="pending", invite_type="direct"),
                name="teaminvite_unique_pending_direct",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invite_type} invite → {self.team.name} ({self.status})"

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def is_usable(self) -> bool:
        return self.status == self.Status.PENDING and not self.is_expired()


# ---------------------------------------------------------------------------
# TeamMembership
# ---------------------------------------------------------------------------

class TeamMembership(models.Model):
    """
    Tracks the membership of a player on a team.

    Lifecycle:
        pending  — a direct invite was sent; the player has not yet responded.
                   Created at the same time as the TeamInvite for direct invites.
        approved — the player accepted (direct) or registered via link invite.
                   PlayerProfile.team is synced to this team at this point.

    The captain is NOT represented here — their team association lives on
    PlayerProfile.team, set by TeamService.create_team on application approval.
    """

    class Status(models.TextChoices):
        PENDING  = "pending",  "Pending"
        APPROVED = "approved", "Approved"

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user      = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    team      = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    status    = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    invite    = models.OneToOneField(
        TeamInvite,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="membership",
    )
    joined_at  = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "team_memberships"
        ordering = ["-joined_at", "-created_at"]
        indexes = [
            models.Index(fields=["team", "status"], name="membership_team_status_idx"),
            models.Index(fields=["user", "status"], name="membership_user_status_idx"),
        ]
        constraints = [
            # One membership row per user per team
            models.UniqueConstraint(
                fields=["user", "team"],
                name="membership_unique_user_team",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} → {self.team.name} ({self.status})"
