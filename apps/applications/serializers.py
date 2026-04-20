from rest_framework import serializers

from apps.teams.models import Team
from apps.users.models import User
from apps.users.serializers import UserSerializer

from .models import Application, FreeAgent

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = {
    Application.Status.APPROVED,
    Application.Status.REJECTED,
}

# Only statuses an admin may transition INTO via the API.
# The full transition graph is enforced by ApplicationService —
# this set acts as a first-pass guard at the serializer level.
_REVIEWABLE_STATUSES = {
    Application.Status.INTERVIEW,
    Application.Status.APPROVED,
    Application.Status.REJECTED,
    Application.Status.WAITLIST,
}

# ---------------------------------------------------------------------------
# Application — read
# ---------------------------------------------------------------------------


class ApplicationSerializer(serializers.ModelSerializer):
    """
    Read representation of an application.
    Includes lightweight summaries of the applicant, team, and reviewer.
    """

    applicant = UserSerializer(read_only=True)
    reviewed_by = UserSerializer(read_only=True)
    team_id = serializers.UUIDField(source="team.id", read_only=True, allow_null=True)
    team_name = serializers.CharField(
        source="team.name", read_only=True, allow_null=True
    )
    preferred_division = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id",
            "applicant",
            "team_id",
            "team_name",
            "type",
            "status",
            "reviewed_by",
            "message",
            "admin_notes",
            "metadata",
            "preferred_division",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_preferred_division(self, obj) -> str:
        profile = getattr(obj.applicant, "profile", None)
        return getattr(profile, "preferred_division", "") or ""


# ---------------------------------------------------------------------------
# Application — create
# ---------------------------------------------------------------------------


class ApplicationCreateSerializer(serializers.Serializer):
    """
    Input for POST /applications.

    Type-specific validation rules:
    ┌───────────────┬──────────────────────────────────────────────────────┐
    │ type          │ constraints                                          │
    ├───────────────┼──────────────────────────────────────────────────────┤
    │ captain       │ team must be absent/null                             │
    │               │ metadata.team_name is required                       │
    ├───────────────┼──────────────────────────────────────────────────────┤
    │ free_agent    │ team (UUID) is required                              │
    │               │ metadata is supplemental only                        │
    └───────────────┴──────────────────────────────────────────────────────┘

    The applicant is always taken from request.user — never from input.
    No create() — the view passes validated_data to ApplicationService.
    """

    type = serializers.ChoiceField(choices=Application.Type.choices)
    team = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )
    metadata = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
    )

    def validate(self, attrs: dict) -> dict:
        app_type = attrs.get("type")
        team = attrs.get("team")
        metadata = attrs.get("metadata", {})

        if app_type == Application.Type.CAPTAIN:
            if team is not None:
                raise serializers.ValidationError(
                    {"team": "Captain applications must not include a team. "
                             "The team will be created upon approval."}
                )
            if not metadata.get("team_name", "").strip():
                raise serializers.ValidationError(
                    {"metadata": "'team_name' is required for captain applications."}
                )

        elif app_type == Application.Type.FREE_AGENT:
            if team is None:
                raise serializers.ValidationError(
                    {"team": "Free-agent applications must specify a target team."}
                )

        return attrs


# ---------------------------------------------------------------------------
# Application — status update (admin action)
# ---------------------------------------------------------------------------


class ApplicationStatusUpdateSerializer(serializers.Serializer):
    """
    Input for PATCH /applications/{id}/status (admin-only).

    Validates:
    - The requested status is a recognised, non-pending value.
    - The application is not already in a terminal state (approved / rejected).

    The full state-machine transition check is performed by
    ApplicationService.update_application_status — this serializer is the
    first lightweight guard only.
    """

    status = serializers.ChoiceField(choices=Application.Status.choices)
    admin_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )

    def validate_status(self, value: str) -> str:
        if value == Application.Status.PENDING:
            raise serializers.ValidationError(
                "Cannot manually set status back to 'pending'."
            )
        if value not in _REVIEWABLE_STATUSES:
            raise serializers.ValidationError(
                f"'{value}' is not a valid review status."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        # Access the current application instance via view context
        application: Application | None = self.context.get("application")
        if application is None:
            return attrs  # context not supplied (e.g. in tests) — skip check

        if application.status in _TERMINAL_STATUSES:
            raise serializers.ValidationError(
                f"Application is already '{application.status}' and cannot be updated."
            )

        if attrs["status"] == application.status:
            raise serializers.ValidationError(
                {"status": f"Application is already in '{application.status}' state."}
            )

        return attrs


# ---------------------------------------------------------------------------
# FreeAgent — read
# ---------------------------------------------------------------------------


class FreeAgentSerializer(serializers.ModelSerializer):
    """Read representation of a free-agent listing."""

    user = UserSerializer(read_only=True)

    class Meta:
        model = FreeAgent
        fields = [
            "id",
            "user",
            "preferred_position",
            "available_since",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# FreeAgent — create / update
# ---------------------------------------------------------------------------


class FreeAgentCreateSerializer(serializers.Serializer):
    """
    Input for POST /free-agents/register.

    The user is always taken from request.user — never from input.
    No create() — the view passes validated_data to
    ApplicationService.register_free_agent.
    """

    preferred_position = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=50,
    )
    available_since = serializers.DateField()
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )

    def validate_available_since(self, value):
        from datetime import date

        if value > date.today():
            raise serializers.ValidationError(
                "available_since cannot be a future date."
            )
        return value


# ---------------------------------------------------------------------------
# Public registration — POST /applications  (no auth required)
# ---------------------------------------------------------------------------


class PublicApplicationSerializer(serializers.Serializer):
    """
    Input for the public registration form (frontend multi-step wizard).

    One submission creates a User, PlayerProfile, and Application atomically.
    No authentication is required — this is the entry point for new participants.

    Field mapping to backend concepts
    ──────────────────────────────────
    applicationType  'free_agent' → Application.type = 'free_agent'  (league registration, no team yet)
                     'full_team'  → Application.type = 'captain'      (team registration)
    reasonForCompeting            → Application.message
    teamName / rosterSize         → Application.metadata  (full_team only)
    nameLogoConfirmation /
      nonGuarantee / codeOfConduct → Application.metadata  (consent record)
    preferredDivision / instagram → PlayerProfile fields
    name / phone / gender         → User fields
    """

    # --- Identity ---
    name = serializers.CharField(max_length=100)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)
    password2 = serializers.CharField(min_length=8, max_length=128, write_only=True)
    phone = serializers.CharField(max_length=20)
    gender = serializers.ChoiceField(choices=["male", "female"])

    # --- Application type ---
    applicationType = serializers.ChoiceField(choices=["free_agent", "full_team"])

    # --- Football profile ---
    preferredDivision = serializers.ChoiceField(choices=["north", "south"])
    instagram = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )

    # --- Application details ---
    reasonForCompeting = serializers.CharField(max_length=2000)

    # --- Full-team only ---
    teamName = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    rosterSize = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=20
    )

    # --- Consent flags ---
    nameLogoConfirmation = serializers.BooleanField()
    nonGuarantee = serializers.BooleanField()
    codeOfConduct = serializers.BooleanField()

    def validate_email(self, value: str) -> str:
        normalised = value.strip().lower()
        if User.objects.filter(email=normalised).exists():
            raise serializers.ValidationError(
                "A user with this email is already registered."
            )
        return normalised

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})

        if attrs["applicationType"] == "full_team":
            if not attrs.get("teamName", "").strip():
                raise serializers.ValidationError(
                    {"teamName": "teamName is required for full team registrations."}
                )
            if not attrs.get("rosterSize"):
                raise serializers.ValidationError(
                    {"rosterSize": "rosterSize is required for full team registrations."}
                )
        return attrs


# ---------------------------------------------------------------------------
# Admin dashboard — flat camelCase representation for the frontend table
# ---------------------------------------------------------------------------


class AdminApplicationFlatSerializer(serializers.ModelSerializer):
    """
    Flat representation consumed by the admin dashboard frontend.

    Field names match what the frontend reads directly.
    Includes both table columns and the full detail fields shown in the
    "View" drawer so the frontend never needs a second API call.

    applicationType maps  captain → 'full_team', free_agent → 'free_agent'
    """

    # ── Table columns ──────────────────────────────────────────────────────────
    name  = serializers.CharField(source="applicant.name",  read_only=True)
    email = serializers.EmailField(source="applicant.email", read_only=True)
    applicationType   = serializers.SerializerMethodField()
    preferredDivision = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    # ── Detail fields (visible in the View drawer only) ────────────────────────
    phone     = serializers.CharField(source="applicant.phone",  read_only=True)
    gender    = serializers.CharField(source="applicant.gender", read_only=True)
    instagram = serializers.SerializerMethodField()
    reasonForCompeting = serializers.CharField(source="message", read_only=True, default="")
    teamName   = serializers.SerializerMethodField()
    rosterSize = serializers.SerializerMethodField()
    adminNotes = serializers.CharField(source="admin_notes", read_only=True, default="")

    class Meta:
        model = Application
        fields = [
            # table
            "id", "name", "email", "applicationType",
            "preferredDivision", "status", "createdAt",
            # detail drawer
            "phone", "gender", "instagram",
            "reasonForCompeting", "teamName", "rosterSize", "adminNotes",
        ]
        read_only_fields = fields

    def get_applicationType(self, obj) -> str:
        return "full_team" if obj.type == Application.Type.CAPTAIN else "free_agent"

    def get_preferredDivision(self, obj) -> str:
        profile = getattr(obj.applicant, "profile", None)
        return getattr(profile, "preferred_division", "") or ""

    def get_instagram(self, obj) -> str:
        profile = getattr(obj.applicant, "profile", None)
        return getattr(profile, "instagram", "") or ""

    def get_teamName(self, obj) -> str:
        return (obj.metadata or {}).get("team_name", "") or ""

    def get_rosterSize(self, obj) -> str:
        value = (obj.metadata or {}).get("roster_size")
        return str(value) if value else ""
