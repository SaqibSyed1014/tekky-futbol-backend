"""
Tests verifying the backend is in sync with the frontend contract
(Milestone 1 — secure login/account system + admin dashboard skeleton).

Covers:
- Login response includes data.token (frontend: auth.setToken(data.token))
- Register response includes data.token
- POST /auth/logout/ blacklists refresh token
- GET /applications/ → { data, total, page, limit } for admins
- PATCH /applications/:id/approve/ → flat camelCase response
- PATCH /applications/:id/reject/  → flat camelCase response
- Response field names match exactly what AdminClient.js reads
"""
from django.urls import reverse
from rest_framework import status

from apps.applications.models import Application
from apps.users.tests.base import BaseAPITestCase, TEST_PASSWORD

LOGIN_URL = reverse("auth:login")
REGISTER_URL = reverse("auth:register")
LOGOUT_URL = reverse("auth:logout")
APPLICATIONS_URL = reverse("applications:create")  # GET admin list / POST registration


def approve_url(pk):
    return reverse("applications:approve", kwargs={"pk": str(pk)})


def reject_url(pk):
    return reverse("applications:reject", kwargs={"pk": str(pk)})


# ===========================================================================
# Token alias — login and register
# ===========================================================================


class LoginTokenAliasTests(BaseAPITestCase):
    """POST /auth/login/ must return data.token (frontend alias for data.access)."""

    def setUp(self):
        self.player = self.create_player(email="login_alias@test.com")

    def test_login_response_contains_token_key(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "login_alias@test.com", "password": TEST_PASSWORD},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.assertIn("token", response.data, "data.token must be present for frontend")

    def test_login_token_equals_access(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "login_alias@test.com", "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(response.data["token"], response.data["access"])


class RegisterTokenAliasTests(BaseAPITestCase):
    """POST /auth/register/ must also return data.token."""

    def test_register_response_contains_token_key(self):
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "reg_alias@test.com",
                "password": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
                "role": "player",
            },
            format="json",
        )
        self.assert_status(response, status.HTTP_201_CREATED)
        self.assertIn("token", response.data, "data.token must be present for frontend")

    def test_register_token_equals_access(self):
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "reg_alias2@test.com",
                "password": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
                "role": "player",
            },
            format="json",
        )
        self.assertEqual(response.data["token"], response.data["access"])


# ===========================================================================
# Logout
# ===========================================================================


class LogoutViewTests(BaseAPITestCase):
    """POST /auth/logout/ — blacklists refresh token, always returns 200."""

    def setUp(self):
        self.player = self.create_player(email="logout@test.com")

    def _get_tokens(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": "logout@test.com", "password": TEST_PASSWORD},
            format="json",
        )
        return response.data["access"], response.data["refresh"]

    def test_logout_authenticated_returns_200(self):
        access, refresh = self._get_tokens()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.post(LOGOUT_URL, {"refresh": refresh}, format="json")
        self.assert_status(response, status.HTTP_200_OK)

    def test_logout_without_refresh_body_still_returns_200(self):
        """Frontend may not always send refresh token — must not error."""
        access, _ = self._get_tokens()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.post(LOGOUT_URL, {}, format="json")
        self.assert_status(response, status.HTTP_200_OK)

    def test_logout_unauthenticated_returns_401(self):
        response = self.client.post(LOGOUT_URL, {}, format="json")
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)


# ===========================================================================
# Frontend admin application list — GET /applications/
# ===========================================================================


class FrontendAdminApplicationListTests(BaseAPITestCase):
    """GET /applications/ — returns { data, total, page, limit } for admins."""

    def setUp(self):
        self.admin = self.create_admin()
        self.player = self.create_player(email="fa_list_player@test.com")
        captain = self.create_player(email="fa_list_cap@test.com")
        team = self.create_team(captain, name="FA List FC")
        self.app = self.create_free_agent_application(self.player, team)

    def test_admin_get_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        self.assert_status(response, status.HTTP_200_OK)

    def test_response_has_data_total_page_limit_keys(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        for key in ("data", "total", "page", "limit"):
            self.assertIn(key, response.data, f"Key '{key}' missing from response")

    def test_data_is_a_list(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        self.assertIsInstance(response.data["data"], list)

    def test_total_reflects_count(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        self.assertEqual(response.data["total"], 1)

    def test_page_defaults_to_1(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        self.assertEqual(response.data["page"], 1)

    def test_limit_defaults_to_20(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        self.assertEqual(response.data["limit"], 20)

    def test_page_and_limit_params_are_respected(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL, {"page": "1", "limit": "5"})
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["limit"], 5)

    def test_application_item_has_required_camelcase_fields(self):
        """AdminClient.js reads: app.name, app.email, app.applicationType,
        app.preferredDivision, app.status, app.createdAt, app.id."""
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        item = response.data["data"][0]
        for field in ("id", "name", "email", "applicationType", "preferredDivision", "status", "createdAt"):
            self.assertIn(field, item, f"Field '{field}' missing from application item")

    def test_name_field_comes_from_applicant(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        item = response.data["data"][0]
        self.assertEqual(item["name"], self.player.name)

    def test_email_field_comes_from_applicant(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        item = response.data["data"][0]
        self.assertEqual(item["email"], self.player.email)

    def test_free_agent_type_maps_to_free_agent(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        item = response.data["data"][0]
        self.assertEqual(item["applicationType"], "free_agent")

    def test_status_filter_returns_matching_items(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL, {"status": "pending"})
        self.assertEqual(response.data["total"], 1)

    def test_status_filter_empty_result(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL, {"status": "approved"})
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(response.data["data"], [])

    def test_invalid_status_returns_400(self):
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL, {"status": "bogus"})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_player_get_returns_403(self):
        """GET /applications/ is admin-only."""
        self.authenticate_as(self.player)
        response = self.client.get(APPLICATIONS_URL)
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_get_returns_401(self):
        response = self.client.get(APPLICATIONS_URL)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_full_team_application_type_maps_to_full_team(self):
        """captain application type must map to 'full_team' for the frontend."""
        captain_app = self.create_captain_application(self.player, team_name="Mapped FC")
        self.authenticate_as(self.admin)
        response = self.client.get(APPLICATIONS_URL)
        # Find the captain application
        captain_items = [
            item for item in response.data["data"]
            if item["applicationType"] == "full_team"
        ]
        self.assertEqual(len(captain_items), 1)


# ===========================================================================
# Frontend approve / reject — PATCH /applications/:id/approve|reject
# ===========================================================================


class FrontendApproveRejectTests(BaseAPITestCase):
    """PATCH /applications/:id/approve and /reject — one-click admin actions."""

    def setUp(self):
        self.admin = self.create_admin()
        self.player = self.create_player(email="ar_player@test.com")
        self.application = self.create_captain_application(
            self.player, team_name="Action FC"
        )

    def test_approve_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(approve_url(self.application.id))
        self.assert_status(response, status.HTTP_200_OK)

    def test_approve_response_status_is_approved(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(approve_url(self.application.id))
        self.assertEqual(response.data["status"], Application.Status.APPROVED)

    def test_approve_response_contains_camelcase_fields(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(approve_url(self.application.id))
        for field in ("id", "name", "email", "applicationType", "status", "createdAt"):
            self.assertIn(field, response.data, f"Field '{field}' missing from approve response")

    def test_reject_returns_200(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(reject_url(self.application.id), {}, format="json")
        self.assert_status(response, status.HTTP_200_OK)

    def test_reject_response_status_is_rejected(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(reject_url(self.application.id), {}, format="json")
        self.assertEqual(response.data["status"], Application.Status.REJECTED)

    def test_reject_with_reason_stored_as_admin_notes(self):
        """reason body param maps to admin_notes on the application."""
        self.authenticate_as(self.admin)
        self.client.patch(
            reject_url(self.application.id),
            {"reason": "Not enough info provided."},
            format="json",
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.admin_notes, "Not enough info provided.")

    def test_reject_response_contains_camelcase_fields(self):
        self.authenticate_as(self.admin)
        response = self.client.patch(reject_url(self.application.id), {}, format="json")
        for field in ("id", "name", "email", "applicationType", "status", "createdAt"):
            self.assertIn(field, response.data, f"Field '{field}' missing from reject response")

    def test_approve_already_terminal_returns_error(self):
        """Cannot approve an already-rejected application."""
        self.authenticate_as(self.admin)
        self.client.patch(reject_url(self.application.id), {}, format="json")
        response = self.client.patch(approve_url(self.application.id))
        self.assertIn(response.status_code, (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ))

    def test_approve_unauthenticated_returns_401(self):
        response = self.client.patch(approve_url(self.application.id))
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_approve_player_returns_403(self):
        self.authenticate_as(self.player)
        response = self.client.patch(approve_url(self.application.id))
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_reject_unauthenticated_returns_401(self):
        response = self.client.patch(reject_url(self.application.id), {}, format="json")
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_reject_player_returns_403(self):
        self.authenticate_as(self.player)
        response = self.client.patch(reject_url(self.application.id), {}, format="json")
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_approve_unknown_pk_returns_404(self):
        import uuid
        self.authenticate_as(self.admin)
        response = self.client.patch(approve_url(uuid.uuid4()))
        self.assert_status(response, status.HTTP_404_NOT_FOUND)
