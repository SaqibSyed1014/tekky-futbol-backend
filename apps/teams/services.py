import logging

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.exceptions import (
    InviteExpiredError,
    InviteInvalidError,
    InvalidRoleError,
    PlayerAlreadyInvitedError,
    PlayerAlreadyOnTeamError,
    PlayerNotOnTeamError,
    ProfileNotFoundError,
    TeamAlreadyExistsError,
    TeamCapacityExceededError,
)
from apps.users.models import PlayerProfile, User
from apps.users.services import UserService

from .models import Team, TeamInvite, TeamMembership

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TeamService
# ---------------------------------------------------------------------------

class TeamService:
    """
    Handles team creation and captain management.

    Invariant enforced here:
        One captain  → one team  (also guaranteed at DB level via OneToOneField)
    """

    @staticmethod
    def _assert_is_captain_eligible(user: User) -> None:
        if user.role != User.Role.PLAYER:
            raise InvalidRoleError(
                f"User '{user.email}' has role='{user.role}'. "
                "Only players can become captains."
            )
        if user.is_captain or hasattr(user, "captained_team"):
            raise TeamAlreadyExistsError(
                f"User '{user.email}' already captains a team."
            )

    @staticmethod
    def _build_unique_slug(name: str) -> str:
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
            status=Team.Status.FORMING,
        )

        captain.is_captain = True
        captain.save(update_fields=["is_captain", "updated_at"])

        profile = getattr(captain, "profile", None)
        if profile is not None:
            profile.team = team
            profile.status = PlayerProfile.Status.ACTIVE
            profile.save(update_fields=["team", "status", "updated_at"])

        logger.info("Team '%s' (%s) created by captain %s", team.name, team.id, captain.id)
        return team

    @staticmethod
    @transaction.atomic
    def remove_player(captain: User, player: User) -> None:
        """
        Captain removes a player from their team.

        Side-effects:
        - Deletes the TeamMembership row.
        - Clears PlayerProfile.team and resets status to FREE_AGENT.
        - Rechecks team status (may revert from official → forming).
        """
        try:
            team = captain.captained_team
        except Team.DoesNotExist:
            raise InvalidRoleError(f"User '{captain.email}' does not captain a team.")

        try:
            membership = TeamMembership.objects.get(
                user=player,
                team=team,
                status=TeamMembership.Status.APPROVED,
            )
        except TeamMembership.DoesNotExist:
            raise PlayerNotOnTeamError(
                f"Player '{player.email}' is not an approved member of team '{team.name}'. "
                "Only approved roster members can be removed by the captain."
            )

        membership.delete()

        # Reset player's profile
        try:
            profile = player.profile
            profile.team = None
            profile.status = PlayerProfile.Status.FREE_AGENT
            profile.save(update_fields=["team", "status", "updated_at"])
        except PlayerProfile.DoesNotExist:
            pass

        # Recheck team status
        InviteService._sync_team_status(team)

        logger.info(
            "Captain %s removed player %s from team %s",
            captain.id, player.id, team.id,
        )


# ---------------------------------------------------------------------------
# InviteService
# ---------------------------------------------------------------------------

class InviteService:
    """
    Owns the full invite lifecycle:

        Direct invite:
            captain selects a registered free-agent player →
            TeamInvite(direct) + TeamMembership(pending) created →
            invite email sent to player →
            player visits /join/:token →
            player accepts  → TeamMembership approved, PlayerProfile synced
            player rejects  → TeamMembership deleted, invite marked rejected

        Link invite:
            captain generates a shareable token (one active link per team) →
            non-registered user clicks link → lands on /register?invite=TOKEN →
            completes registration → InviteService.join_via_link_token() called
            → TeamMembership(approved) created immediately, no pending step
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_team_not_full(team: Team) -> None:
        if team.is_full():
            raise TeamCapacityExceededError(
                f"Team '{team.name}' is already at full capacity ({team.max_players} players)."
            )

    @staticmethod
    def _assert_player_not_on_team(user: User) -> None:
        """
        Raise if the player is already committed to a team.

        Blocked if the player has:
            - an APPROVED membership (admin confirmed), OR
            - a PENDING membership with joined_at set, meaning they accepted
              an invite or signed up via link and are awaiting admin approval.

        A PENDING membership with joined_at=null is a captain-side invite record
        only (player has not responded yet) — that does NOT count as committed.
        """
        from django.db.models import Q
        committed = TeamMembership.objects.filter(
            Q(user=user, status=TeamMembership.Status.APPROVED) |
            Q(user=user, status=TeamMembership.Status.PENDING, joined_at__isnull=False)
        ).exists()
        if committed:
            raise PlayerAlreadyOnTeamError(
                f"Player '{user.email}' is already on a team or awaiting admin approval to join one."
            )

    @staticmethod
    def _sync_team_status(team: Team) -> None:
        """
        Flip team.status between forming ↔ official based on approved
        membership count vs max_players. Always saved — caller is responsible
        for being inside an atomic block.
        """
        count = team.approved_member_count()
        new_status = (
            Team.Status.OFFICIAL if count >= team.max_players else Team.Status.FORMING
        )
        if team.status != new_status:
            team.status = new_status
            team.save(update_fields=["status", "updated_at"])
            logger.info(
                "Team '%s' status → %s (%d/%d players)",
                team.name, new_status, count, team.max_players,
            )

    @staticmethod
    def _get_active_link_invite(team: Team) -> TeamInvite | None:
        return TeamInvite.objects.filter(
            team=team,
            invite_type=TeamInvite.InviteType.LINK,
            status=TeamInvite.Status.PENDING,
        ).first()

    # ------------------------------------------------------------------
    # Direct invite (registered player)
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_direct_invite(captain: User, player: User, team: Team) -> TeamInvite:
        """
        Captain invites a registered free-agent player.

        Creates:
            - TeamInvite(direct, pending)
            - TeamMembership(pending) — visible to captain in pending list

        Raises:
            TeamCapacityExceededError  — team is already full
            PlayerAlreadyOnTeamError   — player is already on a team
            PlayerAlreadyInvitedError  — active direct invite already exists
            InvalidRoleError           — player is not a free agent
        """
        InviteService._assert_team_not_full(team)
        InviteService._assert_player_not_on_team(player)

        # Guard: player must not already have a pending invite to THIS team
        already_invited = TeamInvite.objects.filter(
            team=team,
            invited_user=player,
            status=TeamInvite.Status.PENDING,
        ).exists()
        if already_invited:
            raise PlayerAlreadyInvitedError(
                f"Player '{player.email}' already has a pending invite to '{team.name}'."
            )

        invite = TeamInvite.objects.create(
            team=team,
            invited_by=captain,
            invited_user=player,
            invite_type=TeamInvite.InviteType.DIRECT,
            status=TeamInvite.Status.PENDING,
        )

        # Create membership in pending state so captain can track it
        TeamMembership.objects.create(
            user=player,
            team=team,
            status=TeamMembership.Status.PENDING,
            invite=invite,
        )

        logger.info(
            "Direct invite created: team=%s player=%s invite=%s",
            team.id, player.id, invite.id,
        )
        return invite

    # ------------------------------------------------------------------
    # Link invite (non-registered users)
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def get_or_create_link_invite(captain: User, team: Team) -> TeamInvite:
        """
        Returns the team's active link invite, or creates a new one.

        If an active link invite exists it is returned as-is so the captain
        always gets the same URL until it expires or they explicitly regenerate.
        """
        existing = InviteService._get_active_link_invite(team)
        if existing and not existing.is_expired():
            return existing

        # Revoke any expired/old link invites before creating a fresh one
        TeamInvite.objects.filter(
            team=team,
            invite_type=TeamInvite.InviteType.LINK,
            status=TeamInvite.Status.PENDING,
        ).update(status=TeamInvite.Status.REVOKED, updated_at=timezone.now())

        invite = TeamInvite.objects.create(
            team=team,
            invited_by=captain,
            invited_user=None,
            invite_type=TeamInvite.InviteType.LINK,
            status=TeamInvite.Status.PENDING,
        )

        logger.info("Link invite created: team=%s invite=%s", team.id, invite.id)
        return invite

    @staticmethod
    @transaction.atomic
    def regenerate_link_invite(captain: User, team: Team) -> TeamInvite:
        """Force-create a new link invite, revoking the previous one."""
        TeamInvite.objects.filter(
            team=team,
            invite_type=TeamInvite.InviteType.LINK,
            status=TeamInvite.Status.PENDING,
        ).update(status=TeamInvite.Status.REVOKED, updated_at=timezone.now())

        invite = TeamInvite.objects.create(
            team=team,
            invited_by=captain,
            invited_user=None,
            invite_type=TeamInvite.InviteType.LINK,
            status=TeamInvite.Status.PENDING,
        )
        logger.info("Link invite regenerated: team=%s new_invite=%s", team.id, invite.id)
        return invite

    # ------------------------------------------------------------------
    # Accept / Reject (registered player via direct invite)
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def accept_direct_invite(token: str, player: User) -> TeamMembership:
        """
        Player accepts a direct invite.

        - Validates token, ownership, expiry.
        - Sets joined_at (marks player as committed).
        - Marks the invite ACCEPTED.
        - Leaves TeamMembership in PENDING state — admin must approve before
          the player is counted as a roster member.

        Profile sync and team-status check happen only when an admin later
        calls approve_membership().

        Raises:
            InviteInvalidError         — token not found or wrong player
            InviteExpiredError         — invite past expiry
            TeamCapacityExceededError  — team filled up while invite was pending
            PlayerAlreadyOnTeamError   — player already committed to another team
        """
        invite = InviteService._resolve_direct_invite(token, player)

        InviteService._assert_team_not_full(invite.team)
        InviteService._assert_player_not_on_team(player)

        # Mark player as committed (joined_at set = "player responded yes")
        membership = invite.membership
        membership.joined_at = timezone.now()
        membership.save(update_fields=["joined_at", "updated_at"])

        # Mark invite accepted — status stays PENDING on membership (awaiting admin)
        invite.status = TeamInvite.Status.ACCEPTED
        invite.save(update_fields=["status", "updated_at"])

        logger.info(
            "Invite accepted (awaiting admin approval): invite=%s player=%s team=%s",
            invite.id, player.id, invite.team.id,
        )
        return membership

    @staticmethod
    @transaction.atomic
    def reject_direct_invite(token: str, player: User) -> TeamInvite:
        """
        Player rejects a direct invite.

        - Removes the pending TeamMembership.
        - Marks the invite as rejected.
        """
        invite = InviteService._resolve_direct_invite(token, player)

        # Remove the pending membership row
        TeamMembership.objects.filter(invite=invite).delete()

        invite.status = TeamInvite.Status.REJECTED
        invite.save(update_fields=["status", "updated_at"])

        logger.info(
            "Invite rejected: invite=%s player=%s team=%s",
            invite.id, player.id, invite.team.id,
        )
        return invite

    @staticmethod
    def _resolve_direct_invite(token: str, player: User) -> TeamInvite:
        """
        Look up a direct invite by token and verify it belongs to this player.
        Marks it expired in-place if past expiry before raising.
        """
        try:
            invite = TeamInvite.objects.select_related("team", "membership").get(
                token=token,
                invite_type=TeamInvite.InviteType.DIRECT,
                invited_user=player,
            )
        except TeamInvite.DoesNotExist:
            raise InviteInvalidError("Invite not found or does not belong to you.")

        if invite.status != TeamInvite.Status.PENDING:
            raise InviteInvalidError(
                f"This invite is no longer valid (status: {invite.status})."
            )

        if invite.is_expired():
            invite.status = TeamInvite.Status.EXPIRED
            invite.save(update_fields=["status", "updated_at"])
            raise InviteExpiredError("This invite has expired. Ask your captain to resend it.")

        return invite

    # ------------------------------------------------------------------
    # Join via link (non-registered user, called after signup)
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def join_via_link_token(token: str, user: User) -> TeamMembership:
        """
        Called immediately after a non-registered user completes registration
        using a link invite token.

        - Validates the link invite (pending + not expired).
        - Creates TeamMembership(approved) directly — no pending step.
        - Syncs PlayerProfile.team.
        - Rechecks team status.

        Raises:
            InviteInvalidError         — token not found or wrong type
            InviteExpiredError         — invite past expiry
            TeamCapacityExceededError  — team is full
            PlayerAlreadyOnTeamError   — user is already on a team (edge case)
        """
        try:
            invite = TeamInvite.objects.select_related("team").get(
                token=token,
                invite_type=TeamInvite.InviteType.LINK,
            )
        except TeamInvite.DoesNotExist:
            raise InviteInvalidError("Invite link is invalid.")

        if invite.status != TeamInvite.Status.PENDING:
            raise InviteInvalidError(
                f"This invite link is no longer active (status: {invite.status})."
            )

        if invite.is_expired():
            invite.status = TeamInvite.Status.EXPIRED
            invite.save(update_fields=["status", "updated_at"])
            raise InviteExpiredError("This invite link has expired.")

        InviteService._assert_team_not_full(invite.team)
        InviteService._assert_player_not_on_team(user)

        # Create PENDING membership — admin must approve before the player
        # is counted toward the roster. joined_at is set immediately because
        # the player has committed (unlike a direct invite where the player
        # hasn't responded yet).
        membership = TeamMembership.objects.create(
            user=user,
            team=invite.team,
            status=TeamMembership.Status.PENDING,
            invite=None,          # link invites are reusable; never OneToOne-link them
            joined_at=timezone.now(),
        )

        logger.info(
            "User %s joined team %s via link invite %s (awaiting admin approval)",
            user.id, invite.team.id, invite.id,
        )
        return membership

    # ------------------------------------------------------------------
    # Register + join via link (non-registered user — one atomic flow)
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def register_and_join(
        token: str,
        email: str,
        password: str,
        name: str = "",
        phone: str = "",
        gender: str = "",
        preferred_division: str = "",
    ) -> tuple[User, TeamMembership]:
        """
        Atomic registration + team join for a non-registered user arriving
        via a shareable link invite.

        Steps (all inside a single transaction):
            1. Validate the link invite (pending, not expired, team not full).
            2. Create the User + PlayerProfile via UserService.
            3. Create an approved TeamMembership immediately.
            4. Sync PlayerProfile.team and recheck team status.

        Returns:
            (user, membership) — caller mints JWT from user.

        Raises:
            InviteInvalidError        — token not found / wrong type / already used
            InviteExpiredError        — past expiry date
            TeamCapacityExceededError — team is at max_players
            DuplicateEmailError / ValidationError — email already registered
                (propagated from UserService / Django's create_user)
        """
        # 1. Validate invite (re-uses the same checks as the public endpoint)
        try:
            invite = TeamInvite.objects.select_related("team").get(
                token=token,
                invite_type=TeamInvite.InviteType.LINK,
            )
        except TeamInvite.DoesNotExist:
            raise InviteInvalidError("Invite link is invalid.")

        if invite.status != TeamInvite.Status.PENDING:
            raise InviteInvalidError(
                f"This invite link is no longer active (status: {invite.status})."
            )

        if invite.is_expired():
            invite.status = TeamInvite.Status.EXPIRED
            invite.save(update_fields=["status", "updated_at"])
            raise InviteExpiredError("This invite link has expired.")

        InviteService._assert_team_not_full(invite.team)

        # 2. Create user + PlayerProfile
        user = UserService.create_user(
            email=email,
            password=password,
            role=User.Role.PLAYER,
            name=name,
            phone=phone,
            gender=gender,
        )

        # Save preferred_division on the PlayerProfile if provided
        if preferred_division:
            profile = user.profile
            profile.preferred_division = preferred_division
            profile.save(update_fields=["preferred_division", "updated_at"])

        # 3. Create PENDING membership — admin approves before player counts as
        #    a roster member. joined_at is set because the user has committed.
        membership = TeamMembership.objects.create(
            user=user,
            team=invite.team,
            status=TeamMembership.Status.PENDING,
            invite=None,          # link invites are reusable — never OneToOne-link
            joined_at=timezone.now(),
        )

        logger.info(
            "User %s registered and joined team %s via link invite %s (awaiting admin approval)",
            user.id, invite.team.id, invite.id,
        )
        return user, membership

    # ------------------------------------------------------------------
    # Revoke (captain action)
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def revoke_invite(invite_id: str, captain: User) -> TeamInvite:
        """
        Captain revokes a pending invite (direct or link).

        For direct invites, also removes the pending TeamMembership.
        """
        try:
            team = captain.captained_team
        except Team.DoesNotExist:
            raise InvalidRoleError(f"User '{captain.email}' does not captain a team.")

        try:
            invite = TeamInvite.objects.get(id=invite_id, team=team)
        except TeamInvite.DoesNotExist:
            raise InviteInvalidError("Invite not found on your team.")

        if invite.status != TeamInvite.Status.PENDING:
            raise InviteInvalidError(
                f"Only pending invites can be revoked (current status: {invite.status})."
            )

        # Remove pending membership for direct invites
        if invite.invite_type == TeamInvite.InviteType.DIRECT:
            TeamMembership.objects.filter(invite=invite).delete()

        invite.status = TeamInvite.Status.REVOKED
        invite.save(update_fields=["status", "updated_at"])

        logger.info("Invite %s revoked by captain %s", invite.id, captain.id)
        return invite

    # ------------------------------------------------------------------
    # Admin: approve / reject pending memberships
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def approve_membership(membership_id: str, admin: User) -> TeamMembership:
        """
        Admin approves a pending membership.

        - Validates the reviewer is an admin.
        - Membership must be PENDING with joined_at set (player has committed).
        - Flips status to APPROVED.
        - Syncs PlayerProfile.team and sets status=ACTIVE.
        - Rechecks team status (may flip forming → official).

        Raises:
            InvalidRoleError         — reviewer is not an admin
            InviteInvalidError       — membership not found or not approvable
            TeamCapacityExceededError — team is already full
        """
        if admin.role != User.Role.ADMIN:
            raise InvalidRoleError(
                f"User '{admin.email}' is not an admin and cannot approve memberships."
            )

        try:
            membership = (
                TeamMembership.objects
                .select_related("user", "team", "invite")
                .get(id=membership_id)
            )
        except TeamMembership.DoesNotExist:
            raise InviteInvalidError("Membership not found.")

        if membership.status != TeamMembership.Status.PENDING:
            raise InviteInvalidError(
                f"Only pending memberships can be approved (current status: {membership.status})."
            )

        if membership.joined_at is None:
            raise InviteInvalidError(
                "This membership is a pending invite — the player has not yet accepted. "
                "Only memberships where the player has committed can be approved."
            )

        # Guard against approving into an already-full team
        InviteService._assert_team_not_full(membership.team)

        membership.status = TeamMembership.Status.APPROVED
        membership.save(update_fields=["status", "updated_at"])

        # Sync player profile → sets team FK + status=ACTIVE
        InviteService._sync_player_profile(membership.user, membership.team)

        # Recheck team status (forming → official when roster is complete)
        InviteService._sync_team_status(membership.team)

        logger.info(
            "Membership %s approved by admin %s (user=%s team=%s)",
            membership.id, admin.id, membership.user.id, membership.team.id,
        )
        return membership

    @staticmethod
    @transaction.atomic
    def reject_membership(membership_id: str, admin: User) -> None:
        """
        Admin rejects (removes) a pending membership.

        - Validates the reviewer is an admin.
        - Membership must be PENDING.
        - Deletes the TeamMembership row.
        - Does NOT modify PlayerProfile (the player never officially joined).

        Raises:
            InvalidRoleError   — reviewer is not an admin
            InviteInvalidError — membership not found or not rejectable
        """
        if admin.role != User.Role.ADMIN:
            raise InvalidRoleError(
                f"User '{admin.email}' is not an admin and cannot reject memberships."
            )

        try:
            membership = (
                TeamMembership.objects
                .select_related("user", "team")
                .get(id=membership_id)
            )
        except TeamMembership.DoesNotExist:
            raise InviteInvalidError("Membership not found.")

        if membership.status != TeamMembership.Status.PENDING:
            raise InviteInvalidError(
                f"Only pending memberships can be rejected (current status: {membership.status})."
            )

        user_id = membership.user.id
        team_id = membership.team.id
        membership.delete()

        logger.info(
            "Membership rejected by admin %s (user=%s team=%s)",
            admin.id, user_id, team_id,
        )

    # ------------------------------------------------------------------
    # Validation (public — no auth required)
    # ------------------------------------------------------------------

    @staticmethod
    def validate_link_invite(token: str) -> TeamInvite:
        """
        Validate a link invite token without consuming it.

        Used by the public validate endpoint so the frontend can confirm
        the token is usable before rendering the registration form.

        Checks (in order):
            1. Token exists and is a link-type invite.
            2. Status is pending (not already revoked / expired).
            3. Not past expiry date — marks expired in-place if it is.
            4. Team is not already full.

        Returns the TeamInvite on success.

        Raises:
            InviteInvalidError        — token not found or wrong type / status
            InviteExpiredError        — past expiry date
            TeamCapacityExceededError — team is at max_players
        """
        try:
            invite = TeamInvite.objects.select_related("team").get(
                token=token,
                invite_type=TeamInvite.InviteType.LINK,
            )
        except TeamInvite.DoesNotExist:
            raise InviteInvalidError("Invite link not found.")

        if invite.status != TeamInvite.Status.PENDING:
            raise InviteInvalidError(
                f"This invite link is no longer active (status: {invite.status})."
            )

        if invite.is_expired():
            invite.status = TeamInvite.Status.EXPIRED
            invite.save(update_fields=["status", "updated_at"])
            raise InviteExpiredError("This invite link has expired.")

        InviteService._assert_team_not_full(invite.team)

        return invite

    @staticmethod
    def validate_direct_invite(token: str) -> TeamInvite:
        """
        Validate a direct invite token without consuming it.

        Used by the public join page so it can display team details
        and accept/reject buttons before the player acts.

        Checks (in order):
            1. Token exists and is a direct-type invite.
            2. Status is pending.
            3. Not past expiry — marks expired in-place if it is.
            4. Team is not already full.

        Returns the TeamInvite on success.

        Raises:
            InviteInvalidError        — token not found or wrong type / status
            InviteExpiredError        — past expiry date
            TeamCapacityExceededError — team is at max_players
        """
        try:
            invite = TeamInvite.objects.select_related("team", "team__captain").get(
                token=token,
                invite_type=TeamInvite.InviteType.DIRECT,
            )
        except TeamInvite.DoesNotExist:
            raise InviteInvalidError("Invite not found.")

        if invite.status != TeamInvite.Status.PENDING:
            raise InviteInvalidError(
                f"This invite is no longer active (status: {invite.status})."
            )

        if invite.is_expired():
            invite.status = TeamInvite.Status.EXPIRED
            invite.save(update_fields=["status", "updated_at"])
            raise InviteExpiredError("This invite has expired. Ask your captain to resend it.")

        InviteService._assert_team_not_full(invite.team)

        return invite

    # ------------------------------------------------------------------
    # Shared utility
    # ------------------------------------------------------------------

    @staticmethod
    def _sync_player_profile(user: User, team: Team) -> None:
        """Set PlayerProfile.team, status=ACTIVE, and is_public=True after a successful join."""
        try:
            profile = user.profile
            profile.team = team
            profile.status = PlayerProfile.Status.ACTIVE
            profile.is_public = True
            profile.save(update_fields=["team", "status", "is_public", "updated_at"])
        except PlayerProfile.DoesNotExist:
            logger.warning("No PlayerProfile for user %s — skipping profile sync", user.id)
