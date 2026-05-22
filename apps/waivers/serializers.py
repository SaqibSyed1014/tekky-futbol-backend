from rest_framework import serializers

from .models import CURRENT_WAIVER_VERSION, REQUIRED_CLAUSES, WaiverSignature


# ---------------------------------------------------------------------------
# Input — player/captain submitting the signed waiver
# ---------------------------------------------------------------------------

class WaiverSignatureCreateSerializer(serializers.Serializer):
    """
    Validates the full waiver form submission.

    All 11 clause keys must be present and set to true.
    Adults (is_minor=False) must supply printed_name + signature_image.
    Minors  (is_minor=True)  must supply guardian_signature, guardian_name_printed,
    and guardian_type; guardian_email and guardian_phone are collected but optional.
    Age is no longer restricted at the serializer level — minors are allowed with
    a parent/guardian signature.
    """

    # ── Participant info (all optional — frontend may omit them) ─────────────
    date_of_birth           = serializers.DateField(required=False, allow_null=True, default=None)
    address                 = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    participant_phone       = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)
    medical_conditions      = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    emergency_contact_name  = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    emergency_contact_rel   = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    emergency_contact_phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)

    # ── Age group ─────────────────────────────────────────────────────────────
    is_minor = serializers.BooleanField(required=True)

    # ── Clauses ───────────────────────────────────────────────────────────────
    clauses_initialed = serializers.DictField(child=serializers.BooleanField())

    # ── Sign-off (adult) — required=False at field level; cross-validated below ──
    printed_name    = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    signature_image = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Guardian fields (minor) ───────────────────────────────────────────────
    guardian_signature    = serializers.CharField(required=False, allow_blank=True, default="")
    guardian_name_printed = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    guardian_email        = serializers.EmailField(required=False, allow_blank=True, default="")
    guardian_phone        = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)
    guardian_type         = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_clauses_initialed(self, value):
        missing = [k for k in REQUIRED_CLAUSES if not value.get(k)]
        if missing:
            raise serializers.ValidationError(
                f"The following clauses must be initialled: {', '.join(missing)}"
            )
        return value

    def validate(self, data):
        is_minor = data.get("is_minor", False)

        if is_minor:
            # Guardian fields required for minors
            errors = {}
            if not data.get("guardian_signature", "").strip():
                errors["guardian_signature"] = "Guardian signature is required for minor participants."
            if not data.get("guardian_name_printed", "").strip():
                errors["guardian_name_printed"] = "Guardian printed name is required for minor participants."
            guardian_type = data.get("guardian_type", "").strip()
            if not guardian_type:
                errors["guardian_type"] = "Guardian type (parent or legal_guardian) is required for minor participants."
            elif guardian_type not in ("parent", "legal_guardian"):
                errors["guardian_type"] = "Guardian type must be 'parent' or 'legal_guardian'."
            if errors:
                raise serializers.ValidationError(errors)
        else:
            # Adult fields required for non-minors
            errors = {}
            if not data.get("printed_name", "").strip():
                errors["printed_name"] = "Printed name is required."
            if not data.get("signature_image", "").strip():
                errors["signature_image"] = "A signature is required."
            if errors:
                raise serializers.ValidationError(errors)

        return data


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
            "is_minor",
            "printed_name",
            "guardian_name_printed",
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
            "participant_phone",
            "is_minor",
            "printed_name",
            "guardian_name_printed",
            "guardian_type",
            "guardian_email",
            "guardian_phone",
            "signed_at",
            "ip_address",
        ]
        read_only_fields = fields
