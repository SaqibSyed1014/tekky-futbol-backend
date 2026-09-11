from rest_framework import serializers

from .models import ShopOrder


class ShopOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShopOrder
        fields = [
            "id",
            "product_name",
            "amount_cents",
            "status",
            "created_at",
        ]
        read_only_fields = fields
