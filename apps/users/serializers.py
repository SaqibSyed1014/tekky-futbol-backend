from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import PlayerProfile, User

# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class UserSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a user.
    Password is never included in any response.
    """

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "phone",
            "gender",
            "role",
            "is_captain",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    """
    Input for POST /auth/register.

    Validates:
    - Email is unique and normalised to lowercase.
    - Password meets Django's configured password validators.
    - password and password2 match.
    - Role is a valid User.Role choice.
    - Admins cannot be self-registered (role=admin is rejected here;
      admin creation is an internal operation done via the admin panel
      or a privileged endpoint).

    No create() — the view passes validated_data to UserService.create_user.
    """

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )
    password2 = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        label="Confirm password",
    )
    role = serializers.ChoiceField(
        choices=User.Role.choices,
        default=User.Role.PLAYER,
    )

    def validate_email(self, value: str) -> str:
        normalised = value.strip().lower()
        if User.objects.filter(email=normalised).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )
        return normalised

    def validate_role(self, value: str) -> str:
        if value == User.Role.ADMIN:
            raise serializers.ValidationError(
                "Admin accounts cannot be self-registered."
            )
        return value

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError(
                {"password2": "Passwords do not match."}
            )
        attrs.pop("password2")
        return attrs


# ---------------------------------------------------------------------------
# PlayerProfile
# ---------------------------------------------------------------------------


class PlayerProfileSerializer(serializers.ModelSerializer):
    """
    Read representation of a player profile.
    Includes a lightweight user summary and team reference.
    """

    user = UserSerializer(read_only=True)
    # Expose team as a UUID on read; views that need the full Team object
    # can use the dedicated TeamSerializer there.
    team_id   = serializers.UUIDField(source="team.id",   read_only=True, allow_null=True)
    team_name = serializers.CharField(source="team.name", read_only=True, allow_null=True)
    team_slug = serializers.SlugField(source="team.slug", read_only=True, allow_null=True)

    class Meta:
        model = PlayerProfile
        fields = [
            "id",
            "user",
            "team_id",
            "team_name",
            "team_slug",
            "position",
            "status",
            "is_public",
            "profile_link",
            "profile_link_status",
            "bio",
            "preferred_division",
            "instagram",
            "date_of_birth",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PlayerProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Input for PATCH /users/profile/me/ — players/captains can edit their own
    descriptive fields.

    status, team, and user are intentionally excluded:
    - status transitions go through PlayerService.
    - team assignment goes through PlayerService / ApplicationService.
    """

    class Meta:
        model = PlayerProfile
        fields = [
            "position",
            "bio",
            "date_of_birth",
            "preferred_division",
            "instagram",
        ]

    def validate_date_of_birth(self, value):
        from datetime import date

        if value and value >= date.today():
            raise serializers.ValidationError(
                "Date of birth must be in the past."
            )
        return value


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Input for PATCH /users/me/ — players/captains can update their own
    personal fields.

    email, role, is_captain, is_active, and is_staff are intentionally
    excluded (admin-only or system-managed fields).
    """

    class Meta:
        model = User
        fields = ["name", "phone", "gender"]

    def validate_name(self, value: str) -> str:
        v = value.strip()
        if len(v) < 2:
            raise serializers.ValidationError("Name must be at least 2 characters.")
        return v

    def validate_phone(self, value: str) -> str:
        return value.strip()


# ---------------------------------------------------------------------------
# /auth/me — user + profile in a single response
# (defined before CustomTokenObtainPairSerializer so the login response
#  can use this serializer and include waiver_signed in the login payload)
# ---------------------------------------------------------------------------


class UserDetailSerializer(serializers.ModelSerializer):
    """
    Full identity payload returned by GET /auth/me, GET /users/me,
    POST /auth/login, and POST /auth/register.

    Nests the player profile when it exists; null for admin users.
    Includes waiver_signed so the frontend can gate access immediately
    without an extra round-trip after login.
    """

    profile       = PlayerProfileSerializer(read_only=True)
    waiver_signed = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "phone",
            "gender",
            "role",
            "is_captain",
            "is_active",
            "profile",
            "waiver_signed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_waiver_signed(self, obj) -> bool:
        return hasattr(obj, "waiver_signature")


# ---------------------------------------------------------------------------
# JWT — custom token serializer
# ---------------------------------------------------------------------------


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends simplejwt's default serializer to:
    1. Embed lightweight claims (email, role, is_captain) inside the JWT
       payload so the frontend can decode basic identity without an API call.
    2. Include the full UserDetailSerializer payload in the HTTP response
       body (including waiver_signed and profile) so the frontend has
       everything it needs immediately after login.
    """

    @classmethod
    def get_token(cls, user: User):
        token = super().get_token(user)
        # Custom JWT payload claims
        token["email"] = user.email
        token["role"] = user.role
        token["is_captain"] = user.is_captain
        return token

    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        # Re-fetch with select_related so waiver_signed + profile resolve
        # in a single extra query rather than multiple lazy loads.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.select_related(
            "profile__team", "waiver_signature"
        ).get(pk=self.user.pk)
        data["user"] = UserDetailSerializer(user).data
        # 'token' alias so the frontend can do auth.setToken(data.token)
        data["token"] = data["access"]
        return data


# ---------------------------------------------------------------------------
# Admin — user list (optimised flat representation)
# ---------------------------------------------------------------------------


class AdminUserListSerializer(serializers.ModelSerializer):
    """
    Flat representation for the admin user-list endpoint.

    Profile and team fields are denormalised here (no nested serializer) so
    the view can resolve everything with a single select_related query and
    avoid per-row serializer overhead on large result sets.

    SerializerMethodField is used for the chained profile → team path to
    safely handle admin users who have no PlayerProfile.
    """

    profile_status = serializers.SerializerMethodField()
    team_id        = serializers.SerializerMethodField()
    team_name      = serializers.SerializerMethodField()
    waiver_signed  = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "role",
            "is_captain",
            "is_active",
            "profile_status",
            "team_id",
            "team_name",
            "waiver_signed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    # ------------------------------------------------------------------
    # Helpers — all safe against missing profile / team
    # ------------------------------------------------------------------

    def get_profile_status(self, obj) -> str | None:
        profile = getattr(obj, "profile", None)
        return getattr(profile, "status", None)

    def get_team_id(self, obj) -> str | None:
        profile = getattr(obj, "profile", None)
        team = getattr(profile, "team", None)
        return str(team.id) if team else None

    def get_team_name(self, obj) -> str | None:
        profile = getattr(obj, "profile", None)
        team = getattr(profile, "team", None)
        return team.name if team else None

    def get_waiver_signed(self, obj) -> bool:
        return hasattr(obj, "waiver_signature")
