from rest_framework import serializers

from .models import TicketOrder
from .services import ticket_qr_base64


class MyTicketSerializer(serializers.ModelSerializer):
    """Ticket as shown to its owner — the account wallet and the post-checkout success page.

    Excludes stripe_session_id/email: the buyer doesn't need their own
    Stripe internals, and the email field only exists for guest fallback.
    """

    qr_code_base64 = serializers.SerializerMethodField()

    class Meta:
        model = TicketOrder
        fields = [
            "id",
            "tier",
            "division",
            "week_number",
            "apparel_size",
            "fulfillment_method",
            "product_name",
            "amount_cents",
            "status",
            "checked_in_at",
            "created_at",
            "qr_code_base64",
        ]
        read_only_fields = fields

    def get_qr_code_base64(self, obj) -> str:
        return ticket_qr_base64(obj)


class AdminTicketSerializer(serializers.ModelSerializer):
    """Ticket as shown in the admin ticket list — purchaser identity, not QR art."""

    buyer_name = serializers.SerializerMethodField()
    buyer_email = serializers.SerializerMethodField()
    is_guest = serializers.SerializerMethodField()
    checked_in_by_name = serializers.CharField(source="checked_in_by.name", read_only=True, default="")

    class Meta:
        model = TicketOrder
        fields = [
            "id",
            "buyer_name",
            "buyer_email",
            "is_guest",
            "tier",
            "division",
            "week_number",
            "amount_cents",
            "status",
            "checked_in_at",
            "checked_in_by_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_buyer_name(self, obj) -> str:
        return obj.user.name if obj.user else ""

    def get_buyer_email(self, obj) -> str:
        return obj.user.email if obj.user else obj.email

    def get_is_guest(self, obj) -> bool:
        # A blank buyer_name doesn't mean guest — an account holder may just
        # never have filled in their name. Whether a user is attached at all
        # is the actual signal.
        return obj.user_id is None
