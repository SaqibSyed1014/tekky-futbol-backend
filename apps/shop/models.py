import uuid

from django.conf import settings
from django.db import models


class ShopOrder(models.Model):
    """A completed shop purchase, linked to a fan/player when they were signed in."""

    class Status(models.TextChoices):
        PAID = "paid", "Paid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shop_orders",
    )
    email = models.EmailField(blank=True, default="")
    stripe_session_id = models.CharField(max_length=255, unique=True)
    product_name = models.CharField(max_length=500)
    amount_cents = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PAID,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "shop_orders"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email or self.stripe_session_id} — {self.product_name}"
