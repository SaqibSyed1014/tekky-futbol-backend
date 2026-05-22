import uuid

from django.db import models


# The version string embedded in every WaiverSignature record.
# Bump this constant (e.g. "2.0") and add a migration if the waiver text
# ever changes and all users need to re-sign.
CURRENT_WAIVER_VERSION = "1.0"

# Ordered list of clause keys exactly matching the signed waiver document.
# All 12 must be True for a submission to be accepted.
REQUIRED_CLAUSES = [
    "age_18_or_older",
    "voluntary_participation",
    "strenuous_activities",
    "athletic_hazards",
    "unforeseeable_risks",
    "no_implied_warranties",
    "no_lawsuit",
    "release_of_liability",
    "no_medical_personnel",
    "medical_consultation",
    "identity_likeness_grant",
    "liability_limitation",
]


class WaiverSignature(models.Model):
    """
    Legal record of a user signing the TekkyFutbol participant waiver.

    One record per user (OneToOneField).  Presence of this record is the
    gate that determines whether:
      - a player appears in the free-agent pool (visible to captains), and
      - a captain can generate invite links or send direct invites.

    Fields map 1-to-1 to the sections of the paper waiver form:
      Header  — personal info + emergency contact
      Clauses — each of the 12 initialled paragraphs stored as JSON
      Sign-off — printed name + drawn signature image + date

    Audit trail: ip_address + user_agent captured at submission time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        "users.User",
        on_delete=models.PROTECT,   # legal record must survive user soft-delete
        related_name="waiver_signature",
    )

    waiver_version = models.CharField(
        max_length=20,
        default=CURRENT_WAIVER_VERSION,
        db_index=True,
    )

    # ── Participant info (optional — collected by the signing UI when present) ──
    date_of_birth           = models.DateField(null=True, blank=True)
    address                 = models.TextField(blank=True, default="")
    medical_conditions      = models.TextField(blank=True, default="")
    emergency_contact_name  = models.CharField(max_length=100, blank=True, default="")
    emergency_contact_rel   = models.CharField(max_length=50, blank=True, default="", verbose_name="Emergency contact relationship")
    emergency_contact_phone = models.CharField(max_length=20, blank=True, default="")

    # ── 12 initialled clauses ─────────────────────────────────────────────────
    # Stored as {"age_18_or_older": true, "voluntary_participation": true, ...}
    # All 12 keys must be present and true — enforced at the serializer level.
    clauses_initialed = models.JSONField(default=dict)

    # ── Signature block ───────────────────────────────────────────────────────
    printed_name    = models.CharField(max_length=100)
    signature_image = models.TextField()   # base64-encoded PNG from canvas

    # ── Audit metadata ────────────────────────────────────────────────────────
    signed_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    class Meta:
        db_table = "waiver_signatures"
        ordering = ["-signed_at"]
        indexes = [
            models.Index(fields=["waiver_version", "signed_at"], name="waiver_version_signed_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} — waiver v{self.waiver_version} signed {self.signed_at:%Y-%m-%d}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def is_current_version(self) -> bool:
        return self.waiver_version == CURRENT_WAIVER_VERSION

    @property
    def all_clauses_signed(self) -> bool:
        return all(self.clauses_initialed.get(k) for k in REQUIRED_CLAUSES)
