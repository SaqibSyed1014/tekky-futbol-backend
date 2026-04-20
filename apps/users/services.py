import logging

from django.db import transaction

from apps.core.exceptions import (
    InvalidRoleError,
    InvalidStatusTransitionError,
    PlayerAlreadyOnTeamError,
    ProfileNotFoundError,
    TeamCapacityExceededError,
)
from apps.core.transitions import PLAYER_PROFILE_TRANSITIONS

from .models import PlayerProfile, User

logger = logging.getLogger(__name__)


class UserService:
    """
    Handles user creation and role management.
    Every method that writes more than one row runs inside a transaction.
    """

    @staticmethod
    @transaction.atomic
    def create_user(
        email: str,
        password: str | None,
        role: str = User.Role.PLAYER,
        name: str = "",
        phone: str = "",
        gender: str = "",
    ) -> User:
        """
        Create a new User.

        If role is PLAYER, a PlayerProfile is created in the same transaction
        so the user is never left without a profile.

        password=None creates the account with an unusable password (public
        registration flow — the user can set a password later via reset).

        Raises:
            InvalidRoleError: if role value is not a valid User.Role choice.
        """
        valid_roles = {choice[0] for choice in User.Role.choices}
        if role not in valid_roles:
            raise InvalidRoleError(
                f"'{role}' is not a valid role. Choose from: {sorted(valid_roles)}."
            )

        user = User.objects.create_user(
            email=email,
            password=password,
            role=role,
            name=name,
            phone=phone,
            gender=gender,
        )
        logger.info("Created user %s with role=%s", user.id, role)

        if role == User.Role.PLAYER:
            PlayerProfile.objects.create(
                user=user,
                status=PlayerProfile.Status.FREE_AGENT,
            )
            logger.info("Created PlayerProfile for user %s", user.id)

        return user

    @staticmethod
    @transaction.atomic
    def assign_role(user: User, new_role: str) -> User:
        """
        Change a user's role with safety guards.

        Rules:
        - Cannot promote to PLAYER a user who is already PLAYER.
        - Cannot promote to ADMIN a user who currently captains a team
          (captain ownership must be resolved first).
        - Assigning PLAYER to an existing ADMIN creates a PlayerProfile if
          one does not exist.

        Raises:
            InvalidRoleError: on invalid role value or forbidden transition.
        """
        valid_roles = {choice[0] for choice in User.Role.choices}
        if new_role not in valid_roles:
            raise InvalidRoleError(
                f"'{new_role}' is not a valid role. Choose from: {sorted(valid_roles)}."
            )

        if user.role == new_role:
            raise InvalidRoleError(
                f"User already has role '{new_role}'."
            )

        if new_role == User.Role.ADMIN and user.is_captain:
            raise InvalidRoleError(
                "Cannot assign admin role to a user who currently captains a team. "
                "Transfer or dissolve the team first."
            )

        user.role = new_role

        if new_role == User.Role.PLAYER:
            user.is_captain = False
            user.save(update_fields=["role", "is_captain", "updated_at"])
            # Ensure the new player has a profile
            PlayerProfile.objects.get_or_create(
                user=user,
                defaults={"status": PlayerProfile.Status.FREE_AGENT},
            )
        else:
            user.save(update_fields=["role", "updated_at"])

        logger.info("User %s role changed to %s", user.id, new_role)
        return user


class PlayerService:
    """
    Handles player-profile lifecycle: status transitions and team assignment.
    """

    @staticmethod
    def _get_profile(user: User) -> PlayerProfile:
        """Fetch the PlayerProfile or raise a clean domain error."""
        try:
            return user.profile
        except PlayerProfile.DoesNotExist:
            raise ProfileNotFoundError(
                f"No PlayerProfile found for user '{user.email}'. "
                "Ensure the user has role=player."
            )

    @staticmethod
    def _assert_valid_player(user: User) -> None:
        """Guard: only PLAYER role users may have their profile mutated."""
        if user.role != User.Role.PLAYER:
            raise InvalidRoleError(
                f"User '{user.email}' has role='{user.role}'. "
                "Only players have a PlayerProfile."
            )

    @staticmethod
    @transaction.atomic
    def update_player_status(user: User, new_status: str) -> PlayerProfile:
        """
        Transition a player's status following the allowed state machine.

        Allowed transitions (enforced by PLAYER_PROFILE_TRANSITIONS in apps.core.transitions):
            free_agent  → active
            active      → free_agent | inactive | suspended
            inactive    → active | free_agent
            suspended   → inactive

        Raises:
            InvalidRoleError: if the user is not a player.
            ProfileNotFoundError: if the user has no PlayerProfile.
            InvalidStatusTransitionError: if the transition is not permitted.
        """
        PlayerService._assert_valid_player(user)
        profile = PlayerService._get_profile(user)

        PLAYER_PROFILE_TRANSITIONS.validate(profile.status, new_status)

        old_status = profile.status
        profile.status = new_status
        profile.save(update_fields=["status", "updated_at"])

        logger.info(
            "Player %s status: %s → %s",
            user.id, old_status, new_status,
        )
        return profile

    @staticmethod
    @transaction.atomic
    def assign_player_to_team(user: User, team) -> PlayerProfile:
        """
        Place a player on a team.

        Side-effects (all in one transaction):
        - Sets PlayerProfile.team and transitions status to ACTIVE.
        - Deactivates the player's FreeAgent record if one exists.

        Raises:
            InvalidRoleError: if the user is not a player.
            ProfileNotFoundError: if the user has no PlayerProfile.
            PlayerAlreadyOnTeamError: if the player already belongs to a team.
            TeamCapacityExceededError: if the team is at max capacity.
        """
        PlayerService._assert_valid_player(user)
        profile = PlayerService._get_profile(user)

        if profile.team_id is not None:
            raise PlayerAlreadyOnTeamError(
                f"Player '{user.email}' is already on team '{profile.team}'."
            )

        current_count = team.players.filter(
            status=PlayerProfile.Status.ACTIVE
        ).count()
        if current_count >= team.max_players:
            raise TeamCapacityExceededError(
                f"Team '{team.name}' is at full capacity ({team.max_players} players)."
            )

        profile.team = team
        profile.status = PlayerProfile.Status.ACTIVE
        profile.save(update_fields=["team", "status", "updated_at"])

        # Deactivate free-agent listing without deleting it (preserves history)
        try:
            fa = user.free_agent_profile
            if fa.is_active:
                fa.is_active = False
                fa.save(update_fields=["is_active", "updated_at"])
        except Exception:
            pass  # user had no free-agent record — nothing to do

        logger.info(
            "Player %s assigned to team %s",
            user.id, team.id,
        )
        return profile

    @staticmethod
    @transaction.atomic
    def remove_player_from_team(user: User) -> PlayerProfile:
        """
        Remove a player from their current team and revert them to FREE_AGENT.

        Raises:
            InvalidRoleError: if the user is not a player.
            ProfileNotFoundError: if the user has no PlayerProfile.
            InvalidStatusTransitionError: if the player is not currently active.
        """
        PlayerService._assert_valid_player(user)
        profile = PlayerService._get_profile(user)

        if profile.team_id is None:
            raise InvalidStatusTransitionError(
                f"Player '{user.email}' is not currently on any team."
            )

        profile.team = None
        profile.status = PlayerProfile.Status.FREE_AGENT
        profile.save(update_fields=["team", "status", "updated_at"])

        logger.info("Player %s removed from team and set to free_agent", user.id)
        return profile
