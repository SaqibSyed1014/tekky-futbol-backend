import uuid
from decimal import Decimal

from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        PAID      = "paid",      "Paid"
        FAILED    = "failed",    "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        related_name="payment",
    )

    # Our internal reference sent to BoA — used to look up the record on callback
    reference_number = models.CharField(max_length=100, unique=True)

    # Transaction ID returned by BoA on success
    transaction_id = models.CharField(max_length=100, null=True, blank=True)

    amount   = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("700.00"))
    currency = models.CharField(max_length=3, default="USD")

    status  = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} — {self.status} (${self.amount})"
