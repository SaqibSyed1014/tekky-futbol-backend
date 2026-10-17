import uuid

from django.conf import settings
from django.db import models


class TicketOrder(models.Model):
    """
    A match pass purchase, linked to a fan/player when they were signed in,
    or to a guest email otherwise. Created as PENDING (capacity reserved,
    Stripe session open) before payment completes — tickets are not
    refundable, so the capacity hold has to exist before the card is
    charged, not after.
    """

    class Tier(models.TextChoices):
        SINGLE_MATCH = "single_match", "Single Match Pass"
        SUPPORTER_BUNDLE = "supporter_bundle", "Supporter Bundle"
        SEASON_PASS = "season_pass", "Season Access Pass"
        PLAYOFF_PASS = "playoff_pass", "Playoff Match Pass"
        FINALE_PASS = "finale_pass", "Finale Celebration Pass"

    class Division(models.TextChoices):
        NORTH = "north", "North"
        SOUTH = "south", "South"

    class ApparelSize(models.TextChoices):
        S = "S", "S"
        M = "M", "M"
        L = "L", "L"
        XL = "XL", "XL"
        XXL = "XXL", "XXL"

    class Fulfillment(models.TextChoices):
        PICKUP = "pickup", "Pickup at venue"
        SHIP = "ship", "Ship"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CHECKED_IN = "checked_in", "Checked In"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_orders",
    )
    email = models.EmailField(blank=True, default="")
    stripe_session_id = models.CharField(max_length=255, unique=True)

    tier = models.CharField(max_length=20, choices=Tier.choices, db_index=True)
    division = models.CharField(max_length=10, choices=Division.choices, blank=True, default="")
    week_number = models.PositiveSmallIntegerField(null=True, blank=True)

    apparel_size = models.CharField(max_length=4, choices=ApparelSize.choices, blank=True, default="")
    fulfillment_method = models.CharField(max_length=10, choices=Fulfillment.choices, blank=True, default="")
    # References a key in apps.tickets.constants.SUPPORTER_BUNDLE_MERCH[division] —
    # the shop-catalog item the buyer picked for the Supporter Bundle.
    merch_item_id = models.CharField(max_length=40, blank=True, default="")
    # References a key in apps.tickets.constants.SUPPORTER_BUNDLE_COLORS.
    merch_item_color = models.CharField(max_length=20, blank=True, default="")

    product_name = models.CharField(max_length=500)
    amount_cents = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by_staff = models.ForeignKey(
        "Staff",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_checked_in",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ticket_orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["division", "week_number", "tier", "status"], name="ticket_capacity_idx"),
            models.Index(fields=["tier", "status"], name="ticket_tier_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.email or self.stripe_session_id} — {self.product_name}"


class Staff(models.Model):
    """
    A gate-staff roster entry — not a User account, just a name + optional
    email + a 6-digit ID the admin assigns by hand (never auto-generated).
    The unique_id is what a staff member types into the ticket-verify page
    to prove they're the one completing a check-in, instead of a login.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True, default="")
    unique_id = models.CharField(max_length=6, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_staff"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.unique_id})"


class CapacityBucket(models.Model):
    """
    One row per capacity bucket (e.g. "north:3" for a matchday, or
    "season_pass" for a league-wide tier). Holds no data of its own — it
    exists purely so a capacity check can take a row-level lock
    (select_for_update) on something, serializing concurrent reservation
    attempts for the same bucket even before any TicketOrder row exists yet.
    """

    key = models.CharField(max_length=64, primary_key=True)

    class Meta:
        db_table = "ticket_capacity_buckets"
