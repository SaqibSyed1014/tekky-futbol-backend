from rest_framework import serializers

from .models import VALID_KIT_SLUGS, KitOrder, TeamKitSelection


class TeamKitSelectionSerializer(serializers.ModelSerializer):
    """Captain's team kit state returned to both captain and players."""

    class Meta:
        model = TeamKitSelection
        fields = ["id", "kit_slug", "is_locked", "locked_at", "created_at", "updated_at"]
        read_only_fields = fields


class KitSelectSerializer(serializers.Serializer):
    """Input for captain to pick or change a kit (only while not locked)."""

    kit_slug = serializers.ChoiceField(choices=[(s, s) for s in VALID_KIT_SLUGS])


class KitOrderSerializer(serializers.ModelSerializer):
    """A single player/captain's size order — read representation."""

    userName  = serializers.CharField(source="user.name",  read_only=True)
    userEmail = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = KitOrder
        fields = [
            "id", "userName", "userEmail",
            "jersey_size", "shorts_size", "socks_size",
            "name_on_kit", "number_on_kit",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "userName", "userEmail", "created_at", "updated_at"]


class KitOrderSubmitSerializer(serializers.Serializer):
    """Input for submitting or updating own size order."""

    JERSEY_SHORTS_SIZES = ["S", "M", "L", "XL", "XXL"]
    SOCKS_SIZES = ["S", "M", "L", "XL"]

    jersey_size   = serializers.ChoiceField(choices=JERSEY_SHORTS_SIZES)
    shorts_size   = serializers.ChoiceField(choices=JERSEY_SHORTS_SIZES)
    socks_size    = serializers.ChoiceField(choices=SOCKS_SIZES)
    name_on_kit   = serializers.CharField(required=False, allow_blank=True, max_length=20, default="")
    number_on_kit = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_number_on_kit(self, value):
        if value is None:
            return value
        team = self.context.get("team")
        if team and value > team.max_players:
            raise serializers.ValidationError(
                f"Number must be between 1 and {team.max_players} (team size)."
            )
        return value

    def validate(self, attrs):
        # Check number uniqueness within the team (excluding current user's own order)
        team     = self.context.get("team")
        user     = self.context.get("user")
        number   = attrs.get("number_on_kit")

        if team and number is not None:
            qs = KitOrder.objects.filter(team=team, number_on_kit=number)
            if user:
                qs = qs.exclude(user=user)
            if qs.exists():
                raise serializers.ValidationError(
                    {"number_on_kit": f"Number {number} is already taken by another player on this team."}
                )
        return attrs


class AdminKitOrderSerializer(serializers.ModelSerializer):
    """Full kit order row for the admin table."""

    userName  = serializers.CharField(source="user.name",  read_only=True)
    userEmail = serializers.EmailField(source="user.email", read_only=True)
    teamName  = serializers.CharField(source="team.name",  read_only=True)

    class Meta:
        model = KitOrder
        fields = [
            "id", "teamName", "userName", "userEmail",
            "jersey_size", "shorts_size", "socks_size",
            "name_on_kit", "number_on_kit",
            "created_at",
        ]
        read_only_fields = fields


class AdminTeamKitSerializer(serializers.ModelSerializer):
    """
    Admin view: one entry per team showing the selected kit and all player orders.
    """

    teamName    = serializers.CharField(source="team.name",         read_only=True)
    captainName = serializers.CharField(source="team.captain.name", read_only=True)
    captainEmail = serializers.EmailField(source="team.captain.email", read_only=True)
    orders      = serializers.SerializerMethodField()

    class Meta:
        model = TeamKitSelection
        fields = [
            "id", "teamName", "captainName", "captainEmail",
            "kit_slug", "is_locked", "locked_at",
            "orders",
        ]
        read_only_fields = fields

    def get_orders(self, obj: TeamKitSelection):
        orders = KitOrder.objects.filter(team=obj.team).select_related("user")
        return AdminKitOrderSerializer(orders, many=True).data
