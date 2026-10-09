from types import SimpleNamespace
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status

from apps.tickets.models import TicketOrder
from apps.users.tests.base import BaseAPITestCase

CHECKOUT_URL = reverse("tickets:checkout")

FAKE_SESSION = SimpleNamespace(id="cs_test_123", url="https://checkout.stripe.com/test")


def _patched_stripe():
    return patch("apps.tickets.views.stripe.checkout.Session.create", return_value=FAKE_SESSION)


class TicketCheckoutViewTests(BaseAPITestCase):
    def test_guest_single_match_checkout_creates_pending_order(self):
        with _patched_stripe() as mock_create:
            response = self.client.post(CHECKOUT_URL, {
                "tier": "single_match",
                "division": "north",
                "week_number": 3,
            })

        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["checkout_url"], FAKE_SESSION.url)
        mock_create.assert_called_once()

        order = TicketOrder.objects.get(stripe_session_id="cs_test_123")
        self.assertIsNone(order.user)
        self.assertEqual(order.status, TicketOrder.Status.PENDING)
        self.assertEqual(order.amount_cents, 1000)  # server-side price, never trusts client input

    def test_authenticated_purchase_is_linked_to_the_account(self):
        fan = self.create_fan(email="buyer@test.com")
        self.authenticate_as(fan)

        with _patched_stripe():
            response = self.client.post(CHECKOUT_URL, {
                "tier": "single_match",
                "division": "south",
                "week_number": 1,
            })

        self.assert_status(response, status.HTTP_200_OK)
        order = TicketOrder.objects.get(stripe_session_id="cs_test_123")
        self.assertEqual(order.user, fan)

    def test_price_is_server_side_and_ignores_client_amount(self):
        with _patched_stripe():
            response = self.client.post(CHECKOUT_URL, {
                "tier": "single_match",
                "division": "north",
                "week_number": 1,
                "amount": 1,  # attempted tamper — must be ignored
            })

        self.assert_status(response, status.HTTP_200_OK)
        order = TicketOrder.objects.get(stripe_session_id="cs_test_123")
        self.assertEqual(order.amount_cents, 1000)

    def test_bundle_does_not_require_size_or_fulfillment(self):
        """Apparel size / fulfillment are no longer collected at checkout — the
        bundle purchase must succeed without them."""
        with _patched_stripe():
            response = self.client.post(CHECKOUT_URL, {
                "tier": "supporter_bundle",
                "division": "north",
                "week_number": 1,
            })

        self.assert_status(response, status.HTTP_200_OK)
        order = TicketOrder.objects.get(stripe_session_id="cs_test_123")
        self.assertEqual(order.apparel_size, "")
        self.assertEqual(order.fulfillment_method, "")
        self.assertEqual(order.amount_cents, 6000)

    def test_bundle_ignores_size_and_fulfillment_if_sent_anyway(self):
        with _patched_stripe():
            response = self.client.post(CHECKOUT_URL, {
                "tier": "supporter_bundle",
                "division": "north",
                "week_number": 1,
                "apparel_size": "L",
                "fulfillment_method": "ship",
            })

        self.assert_status(response, status.HTTP_200_OK)
        order = TicketOrder.objects.get(stripe_session_id="cs_test_123")
        self.assertEqual(order.apparel_size, "")
        self.assertEqual(order.fulfillment_method, "")

    def test_season_pass_does_not_require_division_or_week(self):
        with _patched_stripe():
            response = self.client.post(CHECKOUT_URL, {"tier": "season_pass"})

        self.assert_status(response, status.HTTP_200_OK)
        order = TicketOrder.objects.get(stripe_session_id="cs_test_123")
        self.assertEqual(order.amount_cents, 8000)
        self.assertEqual(order.division, "")
        self.assertIsNone(order.week_number)

    def test_finale_pass_is_not_purchasable_yet(self):
        """CTA is disabled 'Coming Soon' on the frontend — enforced server-side too."""
        with _patched_stripe() as mock_create:
            response = self.client.post(CHECKOUT_URL, {"tier": "finale_pass"})

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)
        mock_create.assert_not_called()
        self.assertEqual(TicketOrder.objects.count(), 0)

    def test_invalid_division_rejected(self):
        with _patched_stripe() as mock_create:
            response = self.client.post(CHECKOUT_URL, {
                "tier": "single_match",
                "division": "east",
                "week_number": 1,
            })

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)
        mock_create.assert_not_called()

    def test_week_out_of_range_rejected(self):
        with _patched_stripe() as mock_create:
            response = self.client.post(CHECKOUT_URL, {
                "tier": "single_match",
                "division": "north",
                "week_number": 17,
            })

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)
        mock_create.assert_not_called()

    def test_sold_out_matchday_is_rejected_before_reaching_stripe(self):
        for i in range(40):
            TicketOrder.objects.create(
                stripe_session_id=f"seed_{i}",
                tier=TicketOrder.Tier.SINGLE_MATCH,
                division="north",
                week_number=2,
                product_name="Test Pass",
                amount_cents=1000,
                status=TicketOrder.Status.PAID,
            )

        with _patched_stripe() as mock_create:
            response = self.client.post(CHECKOUT_URL, {
                "tier": "single_match",
                "division": "north",
                "week_number": 2,
            })

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)
        mock_create.assert_not_called()
