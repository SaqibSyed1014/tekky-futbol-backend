import uuid

from django.db import models

# All valid kit image slugs — must match files in public/images/kits/
VALID_KIT_SLUGS = [f"north-{i}" for i in range(1, 9)] + [f"south-{i}" for i in range(1, 9)]
KIT_SLUG_CHOICES = [(s, s) for s in VALID_KIT_SLUGS]

SIZES_JERSEY_SHORTS = [("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"), ("XXL", "XXL")]
SIZES_SOCKS = [("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL")]


class TeamKitSelection(models.Model):
    """
    One kit selected per team. Captain picks from the available kit images and
    then locks the choice. Once locked, the kit cannot be changed and players
    can start submitting their size orders.
    """

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team       = models.OneToOneField(
        "teams.Team",
        on_delete=models.PROTECT,
        related_name="kit_selection",
    )
    kit_slug   = models.CharField(max_length=20, choices=KIT_SLUG_CHOICES)
    is_locked  = models.BooleanField(default=False, db_index=True)
    locked_at  = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "team_kit_selections"

    def __str__(self) -> str:
        status = "locked" if self.is_locked else "pending"
        return f"{self.team.name} — {self.kit_slug} ({status})"


class KitOrder(models.Model):
    """
    A single team member's (captain or player) size order for the team kit.
    Submitted after the captain has locked the kit selection.
    Can be updated after initial submission.
    """

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team          = models.ForeignKey(
        "teams.Team",
        on_delete=models.PROTECT,
        related_name="kit_orders",
    )
    user          = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="kit_orders",
    )
    jersey_size   = models.CharField(max_length=5, choices=SIZES_JERSEY_SHORTS)
    shorts_size   = models.CharField(max_length=5, choices=SIZES_JERSEY_SHORTS)
    socks_size    = models.CharField(max_length=5, choices=SIZES_SOCKS)
    name_on_kit   = models.CharField(max_length=20, blank=True, default="")
    number_on_kit = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kit_orders"
        ordering = ["created_at"]
        constraints = [
            # One order per user per team
            models.UniqueConstraint(
                fields=["team", "user"],
                name="kitorder_unique_team_user",
            ),
            # No two players on the same team can have the same jersey number
            models.UniqueConstraint(
                fields=["team", "number_on_kit"],
                condition=models.Q(number_on_kit__isnull=False),
                name="kitorder_unique_team_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} — {self.team.name} kit order"
