"""
Tests for authentication endpoints:
    POST /api/v1/auth/register/
    POST /api/v1/auth/login/
    GET  /api/v1/auth/me/
    GET  /api/v1/users/me/
"""
from django.urls import reverse
from rest_framework import status

from apps.users.models import PlayerProfile, User

from .base import TEST_PASSWORD, BaseAPITestCase


class RegisterViewTests(BaseAPITestCase):
    """POST /auth/register/ — user registration."""

    url = reverse("auth:register")

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_player_registration_returns_201(self):
        data = {
            "email": "new@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
            "role": "player",
        }
        response = self.client.post(self.url, data)
        self.assert_status(response, status.HTTP_201_CREATED)

    def test_registration_response_contains_tokens_and_user(self):
        data = {
            "email": "token@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        }
        response = self.client.post(self.url, data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("user", response.data)

    def test_registration_returns_correct_user_fields(self):
        data = {
            "email": "fields@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
            "role": "player",
        }
        response = self.client.post(self.url, data)
        user_data = response.data["user"]
        self.assertEqual(user_data["email"], "fields@test.com")
        self.assertEqual(user_data["role"], "player")
        self.assertFalse(user_data["is_captain"])
        self.assertIn("id", user_data)

    def test_registration_creates_player_profile(self):
        data = {
            "email": "profile@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
            "role": "player",
        }
        self.client.post(self.url, data)
        user = User.objects.get(email="profile@test.com")
        self.assertTrue(
            PlayerProfile.objects.filter(user=user).exists(),
            "PlayerProfile must be created automatically for player role.",
        )

    def test_registration_sets_player_profile_status_to_free_agent(self):
        data = {
            "email": "status@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        }
        self.client.post(self.url, data)
        user = User.objects.get(email="status@test.com")
        self.assertEqual(user.profile.status, PlayerProfile.Status.FREE_AGENT)

    # ------------------------------------------------------------------
    # Validation failures
    # ------------------------------------------------------------------

    def test_duplicate_email_returns_400(self):
        self.create_player(email="dup@test.com")
        data = {
            "email": "dup@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        }
        response = self.client.post(self.url, data)
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_password_mismatch_returns_400(self):
        data = {
            "email": "mismatch@test.com",
            "password": TEST_PASSWORD,
            "password2": "WrongPass99!",
        }
        response = self.client.post(self.url, data)
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_weak_password_returns_400(self):
        data = {
            "email": "weak@test.com",
            "password": "123",
            "password2": "123",
        }
        response = self.client.post(self.url, data)
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_admin_role_self_registration_blocked(self):
        """Admins cannot be created via the public register endpoint."""
        data = {
            "email": "admin@test.com",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
            "role": "admin",
        }
        response = self.client.post(self.url, data)
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_missing_email_returns_400(self):
        data = {"password": TEST_PASSWORD, "password2": TEST_PASSWORD}
        response = self.client.post(self.url, data)
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)


class LoginViewTests(BaseAPITestCase):
    """POST /auth/login/ — JWT token issuance."""

    url = reverse("auth:login")

    def setUp(self):
        self.user = self.create_player(email="login@test.com")

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_login_returns_200(self):
        response = self.client.post(
            self.url, {"email": "login@test.com", "password": TEST_PASSWORD}
        )
        self.assert_status(response, status.HTTP_200_OK)

    def test_login_response_contains_access_and_refresh_tokens(self):
        response = self.client.post(
            self.url, {"email": "login@test.com", "password": TEST_PASSWORD}
        )
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_response_contains_user_payload(self):
        response = self.client.post(
            self.url, {"email": "login@test.com", "password": TEST_PASSWORD}
        )
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["email"], "login@test.com")

    # ------------------------------------------------------------------
    # Failures
    # ------------------------------------------------------------------

    def test_wrong_password_returns_401(self):
        response = self.client.post(
            self.url, {"email": "login@test.com", "password": "WrongPass!"}
        )
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_email_returns_401(self):
        response = self.client.post(
            self.url, {"email": "ghost@test.com", "password": TEST_PASSWORD}
        )
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_missing_credentials_returns_400(self):
        response = self.client.post(self.url, {})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)


class MeViewTests(BaseAPITestCase):
    """
    GET /auth/me/  — identity endpoint (auth namespace)
    GET /users/me/ — identity endpoint (users namespace)
    Both return the same shape; both are tested.
    """

    auth_me_url = reverse("auth:me")
    users_me_url = reverse("users:me")

    def setUp(self):
        self.player = self.create_player(email="me@test.com")
        self.admin = self.create_admin(email="admin_me@test.com")

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_authenticated_player_gets_200(self):
        self.authenticate_as(self.player)
        response = self.client.get(self.auth_me_url)
        self.assert_status(response, status.HTTP_200_OK)

    def test_response_contains_expected_fields(self):
        self.authenticate_as(self.player)
        response = self.client.get(self.auth_me_url)
        for field in ("id", "email", "role", "is_captain", "is_active", "created_at"):
            self.assertIn(field, response.data, f"Missing field: {field}")

    def test_player_response_includes_profile(self):
        self.authenticate_as(self.player)
        response = self.client.get(self.auth_me_url)
        self.assertIsNotNone(response.data.get("profile"))
        self.assertEqual(response.data["profile"]["status"], "free_agent")

    def test_admin_response_has_null_profile(self):
        """Admin users have no PlayerProfile — profile must be null."""
        self.authenticate_as(self.admin)
        response = self.client.get(self.auth_me_url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertIsNone(response.data.get("profile"))

    def test_users_me_returns_same_data_as_auth_me(self):
        self.authenticate_as(self.player)
        r1 = self.client.get(self.auth_me_url)
        r2 = self.client.get(self.users_me_url)
        self.assertEqual(r1.data["email"], r2.data["email"])
        self.assertEqual(r1.data["role"], r2.data["role"])

    # ------------------------------------------------------------------
    # Auth failures
    # ------------------------------------------------------------------

    def test_unauthenticated_request_returns_401(self):
        response = self.client.get(self.auth_me_url)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_token_returns_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer notavalidtoken")
        response = self.client.get(self.auth_me_url)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)
