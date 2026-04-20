"""
Tests for admin application endpoints:
    GET   /api/v1/admin/applications/       — list all applications
    PATCH /api/v1/admin/applications/{id}/  — update application status
"""
from django.urls import reverse
from rest_framework import status

from apps.applications.models import Application
from apps.teams.models import Team
from apps.users.models import PlayerProfile
from apps.users.tests.base import BaseAPITestCase


ADMIN_LIST_URL = reverse("api_admin:admin_application_list")


def admin_detail_url(pk):
    return reverse("api_admin:admin_application_detail", kwargs={"pk": str(pk)})


# ===========================================================================
# Admin application list — GET /admin/applications/
# ===========================================================================


class AdminApplicationListViewTests(BaseAPITestCase):
    """GET /admin/applications/ — list all applications across the platform."""

    def setUp(self):
        self.admin = self.create_admin()

        # Two separate players with one application each
        self.player1 = self.create_player(email="p1@test.com")
        self.player2 = self.create_player(email="p2@test.com")
        self.captain = self.create_player(email="cap@test.com")
        self.team = self.create_team(self.captain, name="Admin List FC")

        self.app1 = self.create_captain_application(self.player1, team_name="Team Alpha")
        self.app2 = self.create_free_agent_application(self.player2, self.team)

    # -----------------------------------------------------------------------
    # Happy paths
    # -----------------------------------------------------------------------

    def test_admin_list_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL)
        self.assert_status(response, status.HTTP_200_OK)

    def test_admin_list_returns_all_applications(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL)
        self.assertEqual(response.data["count"], 2)

    def test_admin_list_response_is_paginated(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL)
        for key in ("count", "results", "next", "previous"):
            self.assertIn(key, response.data)

    def test_admin_list_includes_applications_from_multiple_players(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL)
        applicant_ids = {r["applicant"]["id"] for r in response.data["results"]}
        self.assertIn(str(self.player1.id), applicant_ids)
        self.assertIn(str(self.player2.id), applicant_ids)

    # -----------------------------------------------------------------------
    # Filtering
    # -----------------------------------------------------------------------

    def test_filter_by_type_captain_returns_only_captain_apps(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"type": "captain"})
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["type"], "captain")

    def test_filter_by_type_free_agent_returns_only_free_agent_apps(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"type": "free_agent"})
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["type"], "free_agent")

    def test_filter_by_status_pending_returns_all(self):
        """Both test applications start as pending."""
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"status": "pending"})
        self.assertEqual(response.data["count"], 2)

    def test_filter_by_status_approved_returns_empty(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"status": "approved"})
        self.assertEqual(response.data["count"], 0)

    def test_filter_by_email_returns_matching_applicant(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"email": "p1@"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["applicant"]["email"], "p1@test.com"
        )

    def test_filter_by_invalid_status_returns_400(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"status": "bogus"})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_invalid_type_returns_400(self):
        self.authenticate_as(self.admin)
        response = self.client.get(ADMIN_LIST_URL, {"type": "unknown"})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    # -----------------------------------------------------------------------
    # Permission checks
    # -----------------------------------------------------------------------

    def test_unauthenticated_returns_401(self):
        response = self.client.get(ADMIN_LIST_URL)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_player_cannot_access_admin_list(self):
        self.authenticate_as(self.player1)
        response = self.client.get(ADMIN_LIST_URL)
        self.assert_status(response, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# Captain application approval — PATCH /admin/applications/{id}/
# ===========================================================================


class AdminCaptainApprovalTests(BaseAPITestCase):
    """Admin approves a captain application → team is created automatically."""

    def setUp(self):
        self.admin = self.create_admin()
        self.player = self.create_player(email="future_captain@test.com")
        self.application = self.create_captain_application(
            self.player, team_name="Approved FC"
        )

    def test_approve_captain_application_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)

    def test_approve_captain_application_status_is_approved(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(response.data["status"], Application.Status.APPROVED)

    def test_approve_captain_application_creates_team(self):
        """Approving a captain application must create the team automatically."""
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assertTrue(
            Team.objects.filter(name="Approved FC").exists(),
            "Team must be created on captain approval.",
        )

    def test_approve_captain_application_sets_is_captain_flag(self):
        """The player's is_captain flag must be True after approval."""
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.player.refresh_from_db()
        self.assertTrue(self.player.is_captain)

    def test_approve_captain_application_records_reviewed_by(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assertIsNotNone(response.data.get("reviewed_by"))
        self.assertEqual(
            response.data["reviewed_by"]["id"], str(self.admin.id)
        )

    def test_reject_captain_application_does_not_create_team(self):
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "rejected"},
            format="json",
        )
        self.assertFalse(
            Team.objects.filter(name="Approved FC").exists(),
            "Team must NOT be created when application is rejected.",
        )

    def test_admin_notes_are_persisted(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "rejected", "admin_notes": "Insufficient info"},
            format="json",
        )
        self.assertEqual(response.data["admin_notes"], "Insufficient info")


# ===========================================================================
# Free-agent application approval — PATCH /admin/applications/{id}/
# ===========================================================================


class AdminFreeAgentApprovalTests(BaseAPITestCase):
    """Admin approves a free_agent application → player is assigned to team."""

    def setUp(self):
        self.admin = self.create_admin()
        self.player = self.create_player(email="free_agent@test.com")
        self.captain = self.create_player(email="team_captain@test.com")
        self.team = self.create_team(self.captain, name="Target FC")
        self.application = self.create_free_agent_application(
            self.player, self.team
        )

    def test_approve_free_agent_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)

    def test_approve_free_agent_assigns_player_to_team(self):
        """PlayerProfile.team must point to the target team after approval."""
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.player.profile.refresh_from_db()
        self.assertEqual(self.player.profile.team, self.team)

    def test_approve_free_agent_sets_profile_status_to_active(self):
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.player.profile.refresh_from_db()
        self.assertEqual(
            self.player.profile.status, PlayerProfile.Status.ACTIVE
        )

    def test_reject_free_agent_does_not_change_player_team(self):
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "rejected"},
            format="json",
        )
        self.player.profile.refresh_from_db()
        self.assertIsNone(self.player.profile.team)


# ===========================================================================
# Intermediate state transitions
# ===========================================================================


class AdminApplicationIntermediateTransitionTests(BaseAPITestCase):
    """Validate admin can move applications through interview/waitlist states."""

    def setUp(self):
        self.admin = self.create_admin()
        self.player = self.create_player(email="transit@test.com")
        self.application = self.create_captain_application(
            self.player, team_name="Transit FC"
        )

    def test_pending_to_interview_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "interview"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "interview")

    def test_pending_to_waitlist_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "waitlist"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "waitlist")

    def test_interview_to_approved_returns_200(self):
        self.authenticate_as(self.admin)
        # Move to interview first
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "interview"},
            format="json",
        )
        # Then approve
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "approved")

    def test_waitlist_to_interview_returns_200(self):
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "waitlist"},
            format="json",
        )
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "interview"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "interview")


# ===========================================================================
# Invalid transitions and terminal state guard
# ===========================================================================


class AdminApplicationInvalidTransitionTests(BaseAPITestCase):
    """Invalid status transitions must be rejected with the appropriate error."""

    def setUp(self):
        self.admin = self.create_admin()
        self.player = self.create_player(email="invalid_transit@test.com")
        self.application = self.create_captain_application(
            self.player, team_name="Invalid FC"
        )

    def test_transition_to_pending_returns_error(self):
        """Re-entering pending is always forbidden."""
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "pending"},
            format="json",
        )
        # Serializer-level guard: pending is not a valid target status
        self.assertIn(response.status_code, (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ))

    def test_transition_from_terminal_approved_returns_error(self):
        """No transitions out of the terminal 'approved' state."""
        self.authenticate_as(self.admin)
        # Approve first
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        # Try to move to rejected from approved
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "rejected"},
            format="json",
        )
        self.assertIn(response.status_code, (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ))

    def test_transition_from_terminal_rejected_returns_error(self):
        """No transitions out of the terminal 'rejected' state."""
        self.authenticate_as(self.admin)
        self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "rejected"},
            format="json",
        )
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assertIn(response.status_code, (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ))

    def test_unknown_application_returns_404(self):
        import uuid
        self.authenticate_as(self.admin)
        response = self.client.patch(
            admin_detail_url(uuid.uuid4()),
            {"status": "approved"},
            format="json",
        )
        self.assert_status(response, status.HTTP_404_NOT_FOUND)

    # -----------------------------------------------------------------------
    # Permission checks
    # -----------------------------------------------------------------------

    def test_unauthenticated_returns_401(self):
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_player_cannot_update_application_status(self):
        self.authenticate_as(self.player)
        response = self.client.patch(
            admin_detail_url(self.application.id),
            {"status": "approved"},
            format="json",
        )
        self.assert_status(response, status.HTTP_403_FORBIDDEN)
