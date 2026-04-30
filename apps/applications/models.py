import uuid

from django.db import models


class FreeAgent(models.Model):
    """
    Represents a player who is available to join a team.
    Created when a player has no team and marks themselves available.
    is_active is set to False (not deleted) when the player joins a team,
    preserving the historical record.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        related_name="free_agent_profile",
    )
    preferred_position = models.CharField(max_length=50, null=True, blank=True)
    available_since = models.DateField()
    notes = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "free_agents"
        indexes = [
            models.Index(fields=["is_active", "available_since"], name="freeagent_active_since_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} (free agent since {self.available_since})"


class Application(models.Model):
    """
    Unified application entity covering two flows:
      - type='captain'    → user applies to register and lead a new team
      - type='free_agent' → free agent applies to join an existing team

    The partial unique constraint prevents a user from submitting
    duplicate pending applications of the same type.

    metadata (JSONField) stores flexible, type-specific supplemental data
    (e.g. preferred kit number, availability schedule, video links).
    """

    class Type(models.TextChoices):
        CAPTAIN = "captain", "Captain"
        FREE_AGENT = "free_agent", "Free Agent"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WAITLIST = "waitlist", "Waitlist"
        INTERVIEW = "interview", "Interview"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applicant = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,   # preserve application history
        related_name="applications",
        db_index=True,
    )
    team = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="applications",
        db_index=True,
    )
    type = models.CharField(max_length=20, choices=Type.choices, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_applications",
    )
    message = models.TextField(null=True, blank=True)
    admin_notes = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # Team logo uploaded at registration time (captain applications only).
    # Stored in S3 when AWS credentials are configured, local disk otherwise.
    logo = models.FileField(upload_to="team_logos/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "applications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["applicant", "type", "status"], name="app_applicant_type_status_idx"),
            models.Index(fields=["team", "status"], name="application_team_status_idx"),
        ]
        constraints = [
            # Partial unique index: a user may not have two pending applications
            # of the same type at the same time.
            models.UniqueConstraint(
                fields=["applicant", "type"],
                condition=models.Q(status="pending"),
                name="unique_pending_application_per_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.applicant.email} — {self.get_type_display()} ({self.get_status_display()})"
