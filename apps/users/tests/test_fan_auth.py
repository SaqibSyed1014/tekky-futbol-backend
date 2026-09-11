"""
Tests for fan registration, login, profile, and OAuth endpoints.
"""
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status

from apps.shop.models import ShopOrder
from apps.users.models import FanProfile, User
from apps.users.tests.base import TEST_PASSWORD, BaseAPITestCase


class FanRegisterViewTests(BaseAPITestCase):
    url = reverse("auth:fan_register")

    def test_fan_registration_returns_201(self):
        response = self.client.post(
            self.url,
            {
                "email": "newfan@test.com",
                "password": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
                "favorite_division": "north",
                "zip_code": "60601",
            },
            format="json",
        )
        self.assert_status(response, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["role"], "fan")
        self.assertIn("token", response.data)
        user = User.objects.get(email="newfan@test.com")
        self.assertTrue(FanProfile.objects.filter(user=user).exists())
        self.assertEqual(user.fan_profile.favorite_division, "north")
        self.assertEqual(user.fan_profile.zip_code, "60601")

    def test_player_register_rejects_fan_role(self):
        response = self.client.post(
            reverse("auth:register"),
            {
                "email": "sneaky@test.com",
                "password": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
                "role": "fan",
            },
            format="json",
        )
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_invalid_zip_returns_400(self):
        response = self.client.post(
            self.url,
            {
                "email": "badzip@test.com",
                "password": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
                "zip_code": "60",
            },
            format="json",
        )
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)


class FanLoginViewTests(BaseAPITestCase):
    url = reverse("auth:fan_login")

    def setUp(self):
        self.fan = self.create_fan(email="fanlogin@test.com")
        self.player = self.create_player(email="playerlogin@test.com")

    def test_fan_login_returns_200(self):
        response = self.client.post(
            self.url,
            {"email": "fanlogin@test.com", "password": TEST_PASSWORD},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["role"], "fan")
        self.assertIn("fan_profile", response.data["user"])

    def test_player_cannot_use_fan_login(self):
        response = self.client.post(
            self.url,
            {"email": "playerlogin@test.com", "password": TEST_PASSWORD},
            format="json",
        )
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_fan_cannot_use_player_login(self):
        response = self.client.post(
            reverse("auth:login"),
            {"email": "fanlogin@test.com", "password": TEST_PASSWORD},
            format="json",
        )
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)


class FanProfileUpdateTests(BaseAPITestCase):
    url = reverse("users:update_fan_profile")

    def setUp(self):
        self.fan = self.create_fan(email="fanprof@test.com")
        self.player = self.create_player(email="playprof@test.com")

    def test_fan_can_update_profile(self):
        self.authenticate_as(self.fan)
        response = self.client.patch(
            self.url,
            {
                "name": "Alex Fan",
                "favorite_division": "south",
                "zip_code": "60614",
                "shipping_address": "123 Pitch Ave",
                "shipping_city": "Chicago",
                "shipping_state": "IL",
                "shirt_size": "L",
            },
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        self.fan.refresh_from_db()
        self.assertEqual(self.fan.name, "Alex Fan")
        self.assertEqual(self.fan.fan_profile.favorite_division, "south")
        self.assertEqual(self.fan.fan_profile.shirt_size, "L")
        self.assertEqual(response.data["email"], "fanprof@test.com")

    def test_email_is_not_changed(self):
        self.authenticate_as(self.fan)
        self.client.patch(
            self.url,
            {"email": "hacker@test.com", "name": "Alex"},
            format="json",
        )
        self.fan.refresh_from_db()
        self.assertEqual(self.fan.email, "fanprof@test.com")

    def test_player_cannot_update_fan_profile(self):
        self.authenticate_as(self.player)
        response = self.client.patch(self.url, {"name": "Nope"}, format="json")
        self.assert_status(response, status.HTTP_403_FORBIDDEN)


class FanOAuthTests(BaseAPITestCase):
    google_url = reverse("auth:oauth_google")
    apple_url = reverse("auth:oauth_apple")

    @patch("apps.users.views.verify_google_token")
    def test_google_sign_in_creates_fan(self, mock_verify):
        mock_verify.return_value = {
            "email": "googlefan@test.com",
            "name": "Google Fan",
            "google_id": "g-123",
        }
        response = self.client.post(
            self.google_url,
            {"id_token": "fake", "favorite_division": "north"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        user = User.objects.get(email="googlefan@test.com")
        self.assertEqual(user.role, User.Role.FAN)
        self.assertEqual(user.google_id, "g-123")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.fan_profile.favorite_division, "north")

    @patch("apps.users.views.verify_google_token")
    def test_google_sign_in_rejects_existing_player_email(self, mock_verify):
        self.create_player(email="taken@test.com")
        mock_verify.return_value = {
            "email": "taken@test.com",
            "name": "Taken",
            "google_id": "g-999",
        }
        response = self.client.post(
            self.google_url, {"id_token": "fake"}, format="json"
        )
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    @patch("apps.users.views.verify_apple_token")
    def test_apple_sign_in_creates_fan(self, mock_verify):
        mock_verify.return_value = {
            "email": "applefan@test.com",
            "apple_id": "a-123",
        }
        response = self.client.post(
            self.apple_url,
            {"id_token": "fake", "name": "Apple Fan"},
            format="json",
        )
        self.assert_status(response, status.HTTP_200_OK)
        user = User.objects.get(email="applefan@test.com")
        self.assertEqual(user.role, User.Role.FAN)
        self.assertEqual(user.apple_id, "a-123")
        self.assertEqual(user.name, "Apple Fan")


class FanOrderHistoryTests(BaseAPITestCase):
    url = reverse("shop:orders")

    def setUp(self):
        self.fan = self.create_fan(email="orders@test.com")

    def test_lists_own_orders(self):
        ShopOrder.objects.create(
            user=self.fan,
            email=self.fan.email,
            stripe_session_id="cs_test_1",
            product_name="North Hoodie",
            amount_cents=8000,
        )
        ShopOrder.objects.create(
            email="someoneelse@test.com",
            stripe_session_id="cs_test_2",
            product_name="Other Item",
            amount_cents=1000,
        )
        self.authenticate_as(self.fan)
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["product_name"], "North Hoodie")

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)
