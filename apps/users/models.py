import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Authentication entity. Email is the login identifier.
    Role and captain flag drive all permission checks.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        PLAYER = "player", "Player"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.PLAYER,
        db_index=True,
    )
    is_captain = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_staff = models.BooleanField(default=False)
    name = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    gender = models.CharField(
        max_length=10,
        choices=[("male", "Male"), ("female", "Female")],
        blank=True,
        default="",
    )
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["role", "is_active"], name="users_role_active_idx"),
            models.Index(fields=["is_captain", "is_active"], name="users_captain_active_idx"),
        ]

    def __str__(self) -> str:
        return self.email


class PlayerProfile(models.Model):
    """
    Extended profile for role=player users.
    Tracks team membership and player lifecycle status.
    OneToOne with User — created when a user registers as a player.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FREE_AGENT = "free_agent", "Free Agent"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    team = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="players",
        db_index=True,
    )
    position = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.FREE_AGENT,
        db_index=True,
    )
    bio = models.TextField(null=True, blank=True)
    preferred_division = models.CharField(
        max_length=10,
        choices=[("north", "North"), ("south", "South")],
        blank=True,
        default="",
    )
    instagram = models.CharField(max_length=100, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "player_profiles"
        indexes = [
            models.Index(fields=["team", "status"], name="playerprofile_team_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(date_of_birth__isnull=True) | models.Q(date_of_birth__gt="1900-01-01"),
                name="playerprofile_valid_dob",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} — {self.get_status_display()}"
