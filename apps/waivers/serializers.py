from datetime import date

from rest_framework import serializers

from .models import CURRENT_WAIVER_VERSION, REQUIRED_CLAUSES, WaiverSignature


# ---------------------------------------------------------------------------
# Input — player/captain submitting the signed waiver
# ---------------------------------------------------------------------------

class WaiverSignatureCreateSerializer(serializers.Serializer):
    """
    Validates the full waiver form submission.

    All 12 clause keys must be present and set to true.
    The user must be 18+ (date_of_birth check).
    Signature image must be a non-empty base64 string.
    """

    # ── Participant info (all optional — frontend may omit them) ─────────────
    date_of_birth           = serializers.DateField(required=False, allow_null=True, default=None)
    address                 = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    medical_conditions      = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    emergency_contact_name  = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    emergency_contact_rel   = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    emergency_contact_phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)

    # ── Clauses ───────────────────────────────────────────────────────────────
    clauses_initialed = serializers.DictField(child=serializers.BooleanField())

    # ── Sign-off ──────────────────────────────────────────────────────────────
    printed_name    = serializers.CharField(max_length=100)
    signature_image = serializers.CharField()   # base64 PNG

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_date_of_birth(self, value):
        # Field is optional; only validate age when a value is provided.
        if value is None:
            return value
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError(
                "You must be 18 or older to sign the waiver."
            )
        return value

    def validate_clauses_initialed(self, value):
        missing = [k for k in REQUIRED_CLAUSES if not value.get(k)]
        if missing:
            raise serializers.ValidationError(
                f"The following clauses must be initialled: {', '.join(missing)}"
            )
        return value

    def validate_signature_image(self, value):
        # Accept any non-blank value — canvas PNG (base64) or typed-name string.
        if not value or not value.strip():
            raise serializers.ValidationError("A signature is required.")
        return value.strip()

    def validate_printed_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Printed name is required.")
        return value.strip()


# ---------------------------------------------------------------------------
# Output — player/captain reading their own waiver status
# ---------------------------------------------------------------------------

class WaiverStatusSerializer(serializers.ModelSerializer):
    """
    Lightweight read representation returned after signing or on GET /waivers/me/.
    """
    is_current_version = serializers.BooleanField(read_only=True)

    class Meta:
        model = WaiverSignature
        fields = [
            "id",
            "waiver_version",
            "is_current_version",
            "printed_name",
            "signed_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Admin output — full record with user info
# ---------------------------------------------------------------------------

class AdminWaiverListSerializer(serializers.ModelSerializer):
    """
    Full waiver record for the admin view.
    Includes user identity and all signature metadata.
    """
    user_id    = serializers.UUIDField(source="user.id", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name  = serializers.CharField(source="user.name", read_only=True)
    user_role  = serializers.CharField(source="user.role", read_only=True)
    is_captain = serializers.BooleanField(source="user.is_captain", read_only=True)
    is_current_version = serializers.BooleanField(read_only=True)

    class Meta:
        model = WaiverSignature
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "user_role",
            "is_captain",
            "waiver_version",
            "is_current_version",
            "date_of_birth",
            "emergency_contact_name",
            "emergency_contact_rel",
            "emergency_contact_phone",
            "printed_name",
            "signed_at",
            "ip_address",
        ]
        read_only_fields = fields
