from django.urls import reverse
from rest_framework import status

from apps.tickets.models import TicketOrder
from apps.tickets.services import make_qr_token
from apps.users.tests.base import BaseAPITestCase

CHECK_IN_URL = reverse("tickets:check_in")
ADMIN_LIST_URL = reverse("api_admin:admin_ticket_list")


def _paid_ticket(**kwargs):
    defaults = dict(
        stripe_session_id=f"sess_{TicketOrder.objects.count()}",
        tier=TicketOrder.Tier.SINGLE_MATCH,
        division="north",
        week_number=1,
        product_name="Test Pass",
        amount_cents=1000,
        status=TicketOrder.Status.PAID,
    )
    defaults.update(kwargs)
    return TicketOrder.objects.create(**defaults)


class CheckInPermissionTests(BaseAPITestCase):
    def test_unauthenticated_returns_401(self):
        response = self.client.post(CHECK_IN_URL, {"token": "whatever"})
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_fan_cannot_scan(self):
        self.authenticate_as(self.create_fan())
        response = self.client.post(CHECK_IN_URL, {"token": "whatever"})
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_player_cannot_scan(self):
        self.authenticate_as(self.create_player())
        response = self.client.post(CHECK_IN_URL, {"token": "whatever"})
        self.assert_status(response, status.HTTP_403_FORBIDDEN)


class CheckInBehaviorTests(BaseAPITestCase):
    def setUp(self):
        self.admin = self.create_admin()
        self.authenticate_as(self.admin)

    def test_valid_ticket_is_checked_in(self):
        ticket = _paid_ticket()
        token = make_qr_token(ticket.id)

        response = self.client.post(CHECK_IN_URL, {"token": token})

        self.assert_status(response, status.HTTP_200_OK)
        self.assertFalse(response.data["already_checked_in"])

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketOrder.Status.CHECKED_IN)
        self.assertIsNotNone(ticket.checked_in_at)
        self.assertEqual(ticket.checked_in_by, self.admin)

    def test_second_scan_reports_already_checked_in_with_original_timestamp(self):
        ticket = _paid_ticket()
        token = make_qr_token(ticket.id)

        first = self.client.post(CHECK_IN_URL, {"token": token})
        second = self.client.post(CHECK_IN_URL, {"token": token})

        self.assert_status(second, status.HTTP_200_OK)
        self.assertTrue(second.data["already_checked_in"])
        self.assertEqual(first.data["checked_in_at"], second.data["checked_in_at"])

    def test_pending_ticket_cannot_be_checked_in(self):
        ticket = _paid_ticket(status=TicketOrder.Status.PENDING)
        token = make_qr_token(ticket.id)

        response = self.client.post(CHECK_IN_URL, {"token": token})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_tampered_token_is_rejected(self):
        ticket = _paid_ticket()
        token = make_qr_token(ticket.id)
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

        response = self.client.post(CHECK_IN_URL, {"token": tampered})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketOrder.Status.PAID)  # untouched

    def test_missing_token_returns_400(self):
        response = self.client.post(CHECK_IN_URL, {})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)


class AdminTicketListTests(BaseAPITestCase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(ADMIN_LIST_URL)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_returns_403(self):
        self.authenticate_as(self.create_fan())
        response = self.client.get(ADMIN_LIST_URL)
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_admin_sees_purchaser_identity_and_status(self):
        fan = self.create_fan(email="buyer@test.com")
        fan.name = "Test Buyer"
        fan.save(update_fields=["name"])
        _paid_ticket(user=fan)

        self.authenticate_as(self.create_admin())
        response = self.client.get(ADMIN_LIST_URL)

        self.assert_status(response, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["buyer_email"], "buyer@test.com")
        self.assertEqual(results[0]["buyer_name"], "Test Buyer")
        self.assertEqual(results[0]["status"], "paid")

    def test_account_holder_with_blank_name_is_not_mislabeled_a_guest(self):
        """A logged-in buyer with no `name` set must still be distinguishable
        from a real guest (no account at all) — is_guest is the true signal,
        not an empty buyer_name."""
        fan = self.create_fan(email="noname@test.com")
        _paid_ticket(user=fan)

        self.authenticate_as(self.create_admin())
        response = self.client.get(ADMIN_LIST_URL)

        self.assert_status(response, status.HTTP_200_OK)
        result = response.data["results"][0]
        self.assertEqual(result["buyer_name"], "")
        self.assertFalse(result["is_guest"])

    def test_guest_order_is_flagged_as_guest(self):
        _paid_ticket(user=None, email="guest@test.com")

        self.authenticate_as(self.create_admin())
        response = self.client.get(ADMIN_LIST_URL)

        self.assert_status(response, status.HTTP_200_OK)
        result = response.data["results"][0]
        self.assertTrue(result["is_guest"])

    def test_pending_orders_are_excluded(self):
        _paid_ticket(status=TicketOrder.Status.PENDING)

        self.authenticate_as(self.create_admin())
        response = self.client.get(ADMIN_LIST_URL)

        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)
