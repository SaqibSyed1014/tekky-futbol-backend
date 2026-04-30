import logging
from typing import Any

from django.db import transaction

from apps.core.exceptions import (
    ApplicationRequiresTeamError,
    DuplicateApplicationError,
    InvalidRoleError,
    MissingApplicationMetadataError,
    ProfileNotFoundError,
)
from apps.core.transitions import APPLICATION_TRANSITIONS
from apps.teams.services import TeamService
from apps.users.models import PlayerProfile, User
from apps.users.services import PlayerService

from .models import Application, FreeAgent

logger = logging.getLogger(__name__)


class ApplicationService:
    """
    Owns the full application lifecycle for both application types:

        captain    — player applies to register and lead a new team.
        free_agent — player applies to join an existing team.

    Status transitions are strictly enforced by APPLICATION_TRANSITIONS
    (apps.core.transitions).  Approval triggers downstream side-effects
    via TeamService / PlayerService.

    Captain application metadata contract (required keys):
        team_name  (str) — desired team name
        team_slug  (str, optional) — desired slug; auto-generated if absent

    Free-agent application metadata contract:
        No required keys — metadata is supplemental only.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_no_pending_application(applicant: User, app_type: str) -> None:
        """
        Raise DuplicateApplicationError if a pending application of the same
        type already exists for this user.
        """
        exists = Application.objects.filter(
            applicant=applicant,
            type=app_type,
            status=Application.Status.PENDING,
        ).exists()
        if exists:
            raise DuplicateApplicationError(
                f"User '{applicant.email}' already has a pending "
                f"'{app_type}' application."
            )

    # ------------------------------------------------------------------
    # Pre-condition guards per application type
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_captain_application(applicant: User) -> None:
        """
        Guards specific to captain applications:
        - Applicant must be a player.
        - Applicant must not already be a captain.
        """
        if applicant.role != User.Role.PLAYER:
            raise InvalidRoleError(
                f"User '{applicant.email}' has role='{applicant.role}'. "
                "Only players can apply to become a captain."
            )
        if applicant.is_captain:
            raise InvalidRoleError(
                f"User '{applicant.email}' is already a captain."
            )

    @staticmethod
    def _validate_free_agent_application(applicant: User, team) -> None:
        """
        Guards specific to free-agent applications:
        - Applicant must be a player.
        - A target team must be supplied.
        - Applicant must not already be on a team.
        """
        if applicant.role != User.Role.PLAYER:
            raise InvalidRoleError(
                f"User '{applicant.email}' has role='{applicant.role}'. "
                "Only players can submit free-agent applications."
            )
        if team is None:
            raise ApplicationRequiresTeamError(
                "A free_agent application must specify a target team."
            )
        try:
            profile = applicant.profile
        except PlayerProfile.DoesNotExist:
            raise ProfileNotFoundError(
                f"No PlayerProfile found for '{applicant.email}'."
            )
        if profile.team_id is not None:
            raise InvalidRoleError(
                f"Player '{applicant.email}' is already on team '{profile.team}'. "
                "Leave the current team before applying elsewhere."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_application(
        applicant: User,
        app_type: str,
        team=None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Application:
        """
        Submit a new application.

        For captain applications, metadata must contain 'team_name'.
        For free_agent applications, team must be provided.

        Raises:
            InvalidRoleError
            DuplicateApplicationError
            ApplicationRequiresTeamError
            ProfileNotFoundError
            MissingApplicationMetadataError
        """
        metadata = metadata or {}

        # Type-specific pre-condition checks
        if app_type == Application.Type.CAPTAIN:
            ApplicationService._validate_captain_application(applicant)
            if not metadata.get("team_name"):
                raise MissingApplicationMetadataError(
                    "Captain applications require 'team_name' in metadata."
                )
        elif app_type == Application.Type.FREE_AGENT:
            ApplicationService._validate_free_agent_application(applicant, team)
        else:
            raise InvalidRoleError(
                f"Unknown application type '{app_type}'."
            )

        # Prevent duplicate pending applications of the same type
        ApplicationService._assert_no_pending_application(applicant, app_type)

        application = Application.objects.create(
            applicant=applicant,
            team=team,
            type=app_type,
            status=Application.Status.PENDING,
            message=message,
            metadata=metadata,
        )

        logger.info(
            "Application %s created: type=%s applicant=%s",
            application.id, app_type, applicant.id,
        )
        return application

    # ------------------------------------------------------------------
    # Approval side-effect handlers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _approve_captain_application(application: Application) -> None:
        """
        On approval of a captain application:
        1. Extract team details from metadata.
        2. Delegate team creation to TeamService (which also sets is_captain
           and updates the captain's PlayerProfile).
        3. Back-fill application.team so there's a FK record of which team
           was created as a result of this application.
        """
        metadata = application.metadata
        team_name = metadata.get("team_name")
        if not team_name:
            raise MissingApplicationMetadataError(
                "Cannot approve captain application: 'team_name' missing from metadata."
            )

        # Prefer the uploaded logo URL (S3); fall back to any URL in metadata.
        logo_url = None
        if application.logo:
            raw = application.logo.url
            # Only store full URLs in the URLField; skip relative local-dev paths.
            if raw.startswith("http"):
                logo_url = raw
        if logo_url is None:
            logo_url = metadata.get("team_logo_url")

        team = TeamService.create_team(
            captain=application.applicant,
            name=team_name,
            slug=metadata.get("team_slug"),
            description=metadata.get("team_description"),
            logo_url=logo_url,
            max_players=metadata.get("max_players", 11),
        )

        # Record the resulting team on the application for traceability
        application.team = team

    @staticmethod
    def _approve_free_agent_application(application: Application) -> None:
        """
        On approval of a free-agent application:

        - If the application has a target team (legacy / admin-mediated flow):
          delegate to PlayerService which assigns the player and sets status ACTIVE.
        - If team is None (public registration flow): the player is approved as a
          league participant. Team assignment happens separately when an admin
          matches the player to a team.
        """
        if application.team is None:
            # Public-registration path — no team to assign yet; nothing to do.
            return
        PlayerService.assign_player_to_team(
            user=application.applicant,
            team=application.team,
        )

    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def update_application_status(
        application: Application,
        new_status: str,
        reviewed_by: User,
        admin_notes: str | None = None,
    ) -> Application:
        """
        Transition an application's status.

        Allowed transitions (enforced by APPLICATION_TRANSITIONS in apps.core.transitions):
            pending   → interview | approved | rejected | waitlist
            interview → approved  | rejected | waitlist
            waitlist  → interview | approved | rejected
            approved  → (terminal — irreversible)
            rejected  → (terminal — irreversible)

        Approving a 'captain' application triggers TeamService.create_team.
        Approving a 'free_agent' application triggers PlayerService.assign_player_to_team.

        Raises:
            InvalidRoleError: if reviewer is not an admin.
            InvalidStatusTransitionError: if the transition is not permitted.
            MissingApplicationMetadataError: if approval metadata is incomplete.
            ApplicationRequiresTeamError: if a free_agent approval has no team.
        """
        if reviewed_by.role != User.Role.ADMIN:
            raise InvalidRoleError(
                f"User '{reviewed_by.email}' is not an admin and cannot review applications."
            )

        APPLICATION_TRANSITIONS.validate(application.status, new_status)

        # Run approval side-effects before committing the status change
        if new_status == Application.Status.APPROVED:
            if application.type == Application.Type.CAPTAIN:
                ApplicationService._approve_captain_application(application)
            elif application.type == Application.Type.FREE_AGENT:
                ApplicationService._approve_free_agent_application(application)

        old_status = application.status
        application.status = new_status
        application.reviewed_by = reviewed_by
        if admin_notes is not None:
            application.admin_notes = admin_notes

        application.save(
            update_fields=["status", "reviewed_by", "admin_notes", "team", "updated_at"]
        )

        logger.info(
            "Application %s status: %s → %s (reviewed by %s)",
            application.id, old_status, new_status, reviewed_by.id,
        )
        return application

    @staticmethod
    @transaction.atomic
    def register_and_apply(validated_data: dict, logo_file=None) -> "Application":
        """
        Public registration — creates a User + PlayerProfile + Application
        in one atomic transaction.  No authentication required.

        Field mapping
        ─────────────
        validated_data['applicationType']
            'free_agent' → Application.type = FREE_AGENT  (league registration)
            'full_team'  → Application.type = CAPTAIN     (team registration)
        validated_data['reasonForCompeting'] → Application.message
        validated_data['teamName']           → metadata['team_name']   (full_team only)
        validated_data['rosterSize']         → metadata['roster_size'] (full_team only)
        Consent booleans                     → metadata

        The User is created with an unusable password; the participant can set
        one later via a password-reset flow.
        """
        from apps.users.services import UserService  # avoid circular import at module level

        app_type = (
            Application.Type.CAPTAIN
            if validated_data["applicationType"] == "full_team"
            else Application.Type.FREE_AGENT
        )

        # 1. Create User + PlayerProfile
        user = UserService.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            role=User.Role.PLAYER,
            name=validated_data["name"],
            phone=validated_data["phone"],
            gender=validated_data["gender"],
        )

        # 2. Store football-specific profile fields
        profile = user.profile
        profile.preferred_division = validated_data["preferredDivision"]
        profile.instagram = validated_data.get("instagram", "")
        profile.save(update_fields=["preferred_division", "instagram", "updated_at"])

        # 3. Build metadata — consent record + type-specific data
        metadata: dict = {
            "name_logo_confirmation": validated_data["nameLogoConfirmation"],
            "non_guarantee": validated_data["nonGuarantee"],
            "code_of_conduct": validated_data["codeOfConduct"],
        }
        if app_type == Application.Type.CAPTAIN:
            metadata["team_name"] = validated_data["teamName"]
            metadata["roster_size"] = validated_data.get("rosterSize")

        # 4. Create Application — free_agent registrations have no target team
        #    at submission time; the admin matches players to teams on approval.
        application = Application.objects.create(
            applicant=user,
            team=None,
            type=app_type,
            status=Application.Status.PENDING,
            message=validated_data["reasonForCompeting"],
            metadata=metadata,
        )

        # 5. Attach team logo if provided (captain applications only).
        #    FileField saves to S3 (prod) or local media (dev) automatically.
        if logo_file and app_type == Application.Type.CAPTAIN:
            application.logo = logo_file
            application.save(update_fields=["logo"])

        logger.info(
            "Public registration: user=%s type=%s application=%s",
            user.id, app_type, application.id,
        )
        return application

    @staticmethod
    @transaction.atomic
    def register_free_agent(
        user: User,
        available_since,
        preferred_position: str | None = None,
        notes: str | None = None,
    ) -> FreeAgent:
        """
        Mark a player as a free agent available for recruitment.

        Creates or reactivates a FreeAgent record.
        PlayerProfile.status is transitioned to FREE_AGENT via PlayerService.

        Raises:
            InvalidRoleError: if the user is not a player.
            ProfileNotFoundError: if the user has no PlayerProfile.
            InvalidStatusTransitionError: if the player is already active on a team.
        """
        if user.role != User.Role.PLAYER:
            raise InvalidRoleError(
                f"User '{user.email}' has role='{user.role}'. "
                "Only players can register as free agents."
            )

        try:
            profile = user.profile
        except PlayerProfile.DoesNotExist:
            raise ProfileNotFoundError(
                f"No PlayerProfile found for '{user.email}'."
            )

        if profile.team_id is not None:
            raise InvalidStatusTransitionError(
                f"Player '{user.email}' is currently on team '{profile.team}'. "
                "Leave the team before registering as a free agent."
            )

        # Upsert: reactivate existing record or create a new one
        fa, created = FreeAgent.objects.update_or_create(
            user=user,
            defaults={
                "preferred_position": preferred_position,
                "available_since": available_since,
                "notes": notes,
                "is_active": True,
            },
        )

        # Ensure PlayerProfile status reflects free-agent state
        if profile.status != PlayerProfile.Status.FREE_AGENT:
            PlayerService.update_player_status(user, PlayerProfile.Status.FREE_AGENT)

        action = "created" if created else "reactivated"
        logger.info("FreeAgent record %s for user %s", action, user.id)
        return fa
