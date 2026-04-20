import uuid

from django.db import models


class Team(models.Model):
    """
    A registered football team. Each team has exactly one captain.
    The captain FK is UNIQUE — enforcing the one-captain-one-team constraint
    at the database level.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, db_index=True)
    captain = models.OneToOneField(
        "users.User",
        on_delete=models.RESTRICT,   # cannot delete a user who owns a team
        related_name="captained_team",
        db_index=True,
    )
    description = models.TextField(null=True, blank=True)
    logo_url = models.URLField(null=True, blank=True)
    max_players = models.PositiveSmallIntegerField(default=11)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teams"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"], name="teams_active_name_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(max_players__gt=0) & models.Q(max_players__lte=30),
                name="teams_max_players_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name
