"""
Tests for player-facing application endpoints:
    POST /api/v1/applications/       — public registration form (no auth)
    GET  /api/v1/applications/me/    — list own applications (auth required)
"""
from django.urls import reverse
from rest_framework import status

from apps.applications.models import Application
from apps.users.models import User
from apps.users.tests.base import BaseAPITestCase


CREATE_URL = reverse("applications:create")
MY_LIST_URL = reverse("applications:my_list")

# Base payload that matches the frontend form
_BASE_FREE_AGENT = {
    "applicationType": "free_agent",
    "name": "Jane Player",
    "email": "jane@test.com",
    "password": "TestPass123!",
    "password2": "TestPass123!",
    "phone": "+1-555-0101",
    "gender": "female",
    "preferredDivision": "north",
    "reasonForCompeting": "I love the game and want to compete.",
    "nameLogoConfirmation": True,
    "nonGuarantee": True,
    "codeOfConduct": True,
}

_BASE_FULL_TEAM = {
    "applicationType": "full_team",
    "name": "John Captain",
    "email": "john@test.com",
    "password": "TestPass123!",
    "password2": "TestPass123!",
    "phone": "+1-555-0202",
    "gender": "male",
    "preferredDivision": "south",
    "instagram": "@johncaptain",
    "reasonForCompeting": "My crew is ready to dominate.",
    "teamName": "Apex FC",
    "rosterSize": 11,
    "nameLogoConfirmation": True,
    "nonGuarantee": True,
    "codeOfConduct": True,
}


class PublicRegistrationCreateTests(BaseAPITestCase):
    """POST /applications/ — public registration form, no auth required."""

    # ------------------------------------------------------------------
    # Full-team (captain) registration — happy path
    # ------------------------------------------------------------------

    def test_full_team_registration_returns_201(self):
        response = self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        self.assert_status(response, status.HTTP_201_CREATED)

    def test_full_team_creates_captain_application(self):
        self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        self.assertTrue(
            Application.objects.filter(type=Application.Type.CAPTAIN).exists()
        )

    def test_full_team_application_status_is_pending(self):
        response = self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        self.assertEqual(response.data["status"], Application.Status.PENDING)

    def test_full_team_response_contains_expected_fields(self):
        response = self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        for field in ("id", "type", "status", "applicant", "metadata", "created_at"):
            self.assertIn(field, response.data, f"Missing field: {field}")

    def test_full_team_stores_team_name_in_metadata(self):
        response = self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        self.assertEqual(response.data["metadata"]["team_name"], "Apex FC")

    def test_full_team_stores_roster_size_in_metadata(self):
        response = self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        self.assertEqual(response.data["metadata"]["roster_size"], 11)

    def test_full_team_stores_consent_flags_in_metadata(self):
        response = self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        meta = response.data["metadata"]
        self.assertTrue(meta["name_logo_confirmation"])
        self.assertTrue(meta["non_guarantee"])
        self.assertTrue(meta["code_of_conduct"])

    def test_full_team_creates_user_in_db(self):
        self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        self.assertTrue(User.objects.filter(email="john@test.com").exists())

    def test_full_team_user_has_correct_fields(self):
        self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        user = User.objects.get(email="john@test.com")
        self.assertEqual(user.name, "John Captain")
        self.assertEqual(user.phone, "+1-555-0202")
        self.assertEqual(user.gender, "male")

    def test_full_team_user_has_player_role(self):
        self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        user = User.objects.get(email="john@test.com")
        self.assertEqual(user.role, User.Role.PLAYER)

    def test_full_team_profile_has_division_and_instagram(self):
        self.client.post(CREATE_URL, _BASE_FULL_TEAM, format="json")
        user = User.objects.get(email="john@test.com")
        self.assertEqual(user.profile.preferred_division, "south")
        self.assertEqual(user.profile.instagram, "@johncaptain")

    # ------------------------------------------------------------------
    # Free-agent registration — happy path
    # ------------------------------------------------------------------

    def test_free_agent_registration_returns_201(self):
        response = self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        self.assert_status(response, status.HTTP_201_CREATED)

    def test_free_agent_creates_free_agent_application(self):
        self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        self.assertTrue(
            Application.objects.filter(type=Application.Type.FREE_AGENT).exists()
        )

    def test_free_agent_application_has_no_team(self):
        """Free-agent registrations have no target team at submission time."""
        response = self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        self.assertIsNone(response.data["team_id"])

    def test_free_agent_message_contains_reason_for_competing(self):
        response = self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        self.assertEqual(
            response.data["message"],
            "I love the game and want to compete.",
        )

    def test_free_agent_user_created_with_correct_name(self):
        self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        user = User.objects.get(email="jane@test.com")
        self.assertEqual(user.name, "Jane Player")

    def test_free_agent_profile_preferred_division_stored(self):
        self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        user = User.objects.get(email="jane@test.com")
        self.assertEqual(user.profile.preferred_division, "north")

    # ------------------------------------------------------------------
    # Validation errors
    # ------------------------------------------------------------------

    def test_missing_required_field_returns_400(self):
        payload = {**_BASE_FREE_AGENT}
        del payload["name"]
        response = self.client.post(CREATE_URL, payload, format="json")
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_full_team_without_team_name_returns_400(self):
        payload = {**_BASE_FULL_TEAM, "teamName": ""}
        response = self.client.post(CREATE_URL, payload, format="json")
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_full_team_without_roster_size_returns_400(self):
        payload = {k: v for k, v in _BASE_FULL_TEAM.items() if k != "rosterSize"}
        response = self.client.post(CREATE_URL, payload, format="json")
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_invalid_gender_returns_400(self):
        payload = {**_BASE_FREE_AGENT, "gender": "other"}
        response = self.client.post(CREATE_URL, payload, format="json")
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_invalid_division_returns_400(self):
        payload = {**_BASE_FREE_AGENT, "preferredDivision": "east"}
        response = self.client.post(CREATE_URL, payload, format="json")
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_returns_400(self):
        self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        # Submit again with same email
        response = self.client.post(CREATE_URL, _BASE_FREE_AGENT, format="json")
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)


class PlayerApplicationListViewTests(BaseAPITestCase):
    """GET /applications/me/ — list own applications."""

    def setUp(self):
        self.player = self.create_player(email="lister@test.com")
        self.other_player = self.create_player(email="other@test.com")
        self.admin = self.create_admin()

        # Create one application for self.player
        self.captain = self.create_player(email="cap@test.com")
        self.team = self.create_team(self.captain, name="List FC")
        self.application = self.create_free_agent_application(
            self.player, self.team
        )

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_player_sees_own_applications(self):
        self.authenticate_as(self.player)
        response = self.client.get(MY_LIST_URL)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_player_does_not_see_others_applications(self):
        """other_player has no applications — list must be empty."""
        self.authenticate_as(self.other_player)
        response = self.client.get(MY_LIST_URL)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_response_is_paginated(self):
        self.authenticate_as(self.player)
        response = self.client.get(MY_LIST_URL)
        for key in ("count", "results", "next", "previous"):
            self.assertIn(key, response.data)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def test_filter_by_valid_status_returns_results(self):
        self.authenticate_as(self.player)
        response = self.client.get(MY_LIST_URL, {"status": "pending"})
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_filter_by_non_matching_status_returns_empty(self):
        self.authenticate_as(self.player)
        response = self.client.get(MY_LIST_URL, {"status": "approved"})
        self.assertEqual(response.data["count"], 0)

    def test_filter_by_invalid_status_returns_400(self):
        self.authenticate_as(self.player)
        response = self.client.get(MY_LIST_URL, {"status": "nonexistent"})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------------

    def test_unauthenticated_returns_401(self):
        response = self.client.get(MY_LIST_URL)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_admin_cannot_access_player_list(self):
        self.authenticate_as(self.admin)
        response = self.client.get(MY_LIST_URL)
        self.assert_status(response, status.HTTP_403_FORBIDDEN)
