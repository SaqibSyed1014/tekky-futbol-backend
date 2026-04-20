from rest_framework import serializers

from apps.users.serializers import UserSerializer

from .models import Team

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------


class TeamSerializer(serializers.ModelSerializer):
    """
    Read representation of a team.
    Includes full captain summary and a live player count.
    """

    captain = UserSerializer(read_only=True)
    player_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "slug",
            "captain",
            "description",
            "logo_url",
            "max_players",
            "player_count",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_player_count(self, obj: Team) -> int:
        # Uses the reverse relation defined on PlayerProfile.team
        return obj.players.count()


class TeamCreateSerializer(serializers.Serializer):
    """
    Input for POST /teams (captain-only endpoint).

    The captain is inferred from request.user in the view — it is never
    accepted from the client.

    No create() — the view passes validated_data to TeamService.create_team.
    """

    name = serializers.CharField(max_length=100)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )
    logo_url = serializers.URLField(required=False, allow_null=True)
    max_players = serializers.IntegerField(
        min_value=1,
        max_value=30,
        default=11,
    )

    def validate_name(self, value: str) -> str:
        if Team.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError(
                f"A team named '{value}' already exists."
            )
        return value
