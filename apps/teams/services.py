import logging

from django.db import transaction
from django.utils.text import slugify

from apps.core.exceptions import InvalidRoleError, TeamAlreadyExistsError
from apps.users.models import PlayerProfile, User

from .models import Team

logger = logging.getLogger(__name__)


class TeamService:
    """
    Handles team creation and captain management.

    Invariant enforced here:
        One captain  → one team  (also guaranteed at DB level via OneToOneField)
    """

    @staticmethod
    def _assert_is_captain_eligible(user: User) -> None:
        """
        Guard: the user must be a PLAYER and must not already own a team.

        Raises:
            InvalidRoleError: if the user is not a player.
            TeamAlreadyExistsError: if the user already captains a team.
        """
        if user.role != User.Role.PLAYER:
            raise InvalidRoleError(
                f"User '{user.email}' has role='{user.role}'. "
                "Only players can become captains."
            )

        if user.is_captain or hasattr(user, "captained_team"):
            raise TeamAlreadyExistsError(
                f"User '{user.email}' already captains a team. "
                "A player can only own one team."
            )

    @staticmethod
    def _build_unique_slug(name: str) -> str:
        """
        Generate a slug from name and append a numeric suffix when a collision
        exists, so slugs remain unique without relying on the caller to supply one.
        """
        base = slugify(name)
        slug = base
        counter = 1
        while Team.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    @staticmethod
    @transaction.atomic
    def create_team(
        captain: User,
        name: str,
        description: str | None = None,
        logo_url: str | None = None,
        max_players: int = 11,
        slug: str | None = None,
    ) -> Team:
        """
        Register a new team and assign its captain.

        Side-effects (all in one transaction):
        - Creates the Team row.
        - Sets User.is_captain = True.
        - Sets PlayerProfile.status = ACTIVE and assigns the team.

        Raises:
            InvalidRoleError: if the user is not a player.
            TeamAlreadyExistsError: if the user already captains a team.
        """
        TeamService._assert_is_captain_eligible(captain)

        resolved_slug = slug or TeamService._build_unique_slug(name)

        team = Team.objects.create(
            name=name,
            slug=resolved_slug,
            captain=captain,
            description=description,
            logo_url=logo_url,
            max_players=max_players,
        )

        # Promote captain flag on the user
        captain.is_captain = True
        captain.save(update_fields=["is_captain", "updated_at"])

        # Update the captain's PlayerProfile — they are now active on their own team
        profile = getattr(captain, "profile", None)
        if profile is not None:
            profile.team = team
            profile.status = PlayerProfile.Status.ACTIVE
            profile.save(update_fields=["team", "status", "updated_at"])

        logger.info(
            "Team '%s' (%s) created by captain %s",
            team.name, team.id, captain.id,
        )
        return team
