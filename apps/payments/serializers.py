from rest_framework import serializers

from .models import Payment


class PaymentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "status", "amount", "currency", "paid_at", "created_at"]
        read_only_fields = fields


class AdminPaymentSerializer(serializers.ModelSerializer):
    user_id    = serializers.UUIDField(source="user.id",         read_only=True)
    user_name  = serializers.CharField(source="user.name",       read_only=True)
    user_email = serializers.EmailField(source="user.email",     read_only=True)
    is_captain = serializers.BooleanField(source="user.is_captain", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "user_id",
            "user_name",
            "user_email",
            "is_captain",
            "status",
            "amount",
            "currency",
            "transaction_id",
            "paid_at",
            "created_at",
        ]
        read_only_fields = fields
