from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import FanProfile, PlayerProfile, User

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
        if value in (User.Role.ADMIN, User.Role.FAN):
            raise serializers.ValidationError(
                "This account type cannot be self-registered here."
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
# Fan registration / profile
# ---------------------------------------------------------------------------


class FanRegisterSerializer(serializers.Serializer):
    """Input for POST /auth/fan/register/."""

    email = serializers.EmailField(max_length=254)
    name = serializers.CharField(max_length=100, min_length=2)
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

    def validate_email(self, value: str) -> str:
        normalised = value.strip().lower()
        if User.objects.filter(email=normalised).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )
        return normalised

    def validate_name(self, value: str) -> str:
        return value.strip()

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


class FanProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FanProfile
        fields = [
            "favorite_division",
            "zip_code",
            "shipping_address",
            "shipping_city",
            "shipping_state",
            "shirt_size",
        ]
        read_only_fields = fields


class FanProfileUpdateSerializer(serializers.ModelSerializer):
    """PATCH /users/fan/me/ — name is handled separately on User."""

    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    zip_code = serializers.CharField(required=False, allow_blank=True, max_length=5)

    class Meta:
        model = FanProfile
        fields = [
            "name",
            "favorite_division",
            "zip_code",
            "shipping_address",
            "shipping_city",
            "shipping_state",
            "shirt_size",
        ]

    def validate_name(self, value: str) -> str:
        return value.strip()

    def validate_zip_code(self, value: str) -> str:
        v = (value or "").strip()
        if v and (len(v) != 5 or not v.isdigit()):
            raise serializers.ValidationError("Zip code must be 5 digits.")
        return v

    def validate_favorite_division(self, value: str) -> str:
        return value or ""

    def update(self, instance, validated_data):
        name = validated_data.pop("name", None)
        if name is not None:
            user = instance.user
            user.name = name
            user.save(update_fields=["name", "updated_at"])
        return super().update(instance, validated_data)


class OAuthFanSerializer(serializers.Serializer):
    """Shared input for Google/Apple fan Sign-In."""

    id_token = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    favorite_division = serializers.ChoiceField(
        choices=FanProfile.Division.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    zip_code = serializers.CharField(required=False, allow_blank=True, default="", max_length=5)

    def validate_zip_code(self, value: str) -> str:
        v = (value or "").strip()
        if v and (len(v) != 5 or not v.isdigit()):
            raise serializers.ValidationError("Zip code must be 5 digits.")
        return v


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

    profile        = PlayerProfileSerializer(read_only=True)
    fan_profile    = FanProfileSerializer(read_only=True)
    waiver_signed  = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    has_password   = serializers.SerializerMethodField()

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
            "fan_profile",
            "has_password",
            "waiver_signed",
            "payment_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_waiver_signed(self, obj) -> bool:
        return hasattr(obj, "waiver_signature")

    def get_payment_status(self, obj) -> str | None:
        try:
            return obj.payment.status
        except Exception:
            return None

    def get_has_password(self, obj) -> bool:
        return obj.has_usable_password()


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

    Shared by the single /auth/login/ endpoint used by every role — fan,
    player, captain, and admin all sign in here.
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

        from .services import USER_DETAIL_RELATIONS

        user = User.objects.select_related(*USER_DETAIL_RELATIONS).get(pk=self.user.pk)
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


# ---------------------------------------------------------------------------
# Admin — fan list (flat representation)
# ---------------------------------------------------------------------------


class AdminFanListSerializer(serializers.ModelSerializer):
    """
    Flat representation for the admin fan-list endpoint.

    auth_method reflects how the account was created / is able to sign in:
    'google', 'apple', 'google_apple' (linked both), or 'email' (password only).
    A fan can have both a linked provider and a password (e.g. they signed up
    with Google, then later set a password) — auth_method always reports the
    linked OAuth provider(s) when present, since that's what admins are
    asking to see.
    """

    favorite_division = serializers.SerializerMethodField()
    zip_code           = serializers.SerializerMethodField()
    auth_method        = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "favorite_division",
            "zip_code",
            "auth_method",
            "created_at",
        ]
        read_only_fields = fields

    def get_favorite_division(self, obj) -> str:
        profile = getattr(obj, "fan_profile", None)
        return getattr(profile, "favorite_division", "") or ""

    def get_zip_code(self, obj) -> str:
        profile = getattr(obj, "fan_profile", None)
        return getattr(profile, "zip_code", "") or ""

    def get_auth_method(self, obj) -> str:
        if obj.google_id and obj.apple_id:
            return "google_apple"
        if obj.google_id:
            return "google"
        if obj.apple_id:
            return "apple"
        return "email"
