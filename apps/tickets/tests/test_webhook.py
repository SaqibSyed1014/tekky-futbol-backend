"""
Tests for the ticket branches added to the shared Stripe webhook
(apps/payments/views.py::PaymentCallbackView). Calls the handler methods
directly rather than going through real Stripe signature verification —
that plumbing is already covered by the existing registration-fee webhook,
this just needs to prove the ticket-specific branches behave correctly.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status

from apps.payments.views import PaymentCallbackView
from apps.tickets.models import TicketOrder
from apps.users.tests.base import BaseAPITestCase


def _pending_ticket(session_id="cs_webhook_1", **kwargs):
    defaults = dict(
        stripe_session_id=session_id,
        tier=TicketOrder.Tier.SINGLE_MATCH,
        division="north",
        week_number=1,
        product_name="Test Pass",
        amount_cents=1000,
        status=TicketOrder.Status.PENDING,
    )
    defaults.update(kwargs)
    return TicketOrder.objects.create(**defaults)


class TicketCompletedWebhookTests(BaseAPITestCase):
    def test_marks_guest_ticket_paid_and_sends_confirmation_email(self):
        _pending_ticket()
        session = SimpleNamespace(
            id="cs_webhook_1",
            customer_details=SimpleNamespace(email="guest@test.com", name="Guest Buyer"),
        )

        with patch("apps.tickets.email_service.send_ticket_confirmation") as mock_send:
            PaymentCallbackView()._handle_ticket_completed(session, {"type": "ticket_order"})

        order = TicketOrder.objects.get(stripe_session_id="cs_webhook_1")
        self.assertEqual(order.status, TicketOrder.Status.PAID)
        self.assertEqual(order.email, "guest@test.com")
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs["customer_email"], "guest@test.com")

    def test_account_holder_ticket_paid_without_sending_email(self):
        """Account holders see their ticket in the wallet — no email needed."""
        fan = self.create_fan(email="fan@test.com")
        _pending_ticket(user=fan)
        session = SimpleNamespace(
            id="cs_webhook_1",
            customer_details=SimpleNamespace(email="fan@test.com", name="Fan"),
        )

        with patch("apps.tickets.email_service.send_ticket_confirmation") as mock_send:
            PaymentCallbackView()._handle_ticket_completed(session, {"type": "ticket_order"})

        order = TicketOrder.objects.get(stripe_session_id="cs_webhook_1")
        self.assertEqual(order.status, TicketOrder.Status.PAID)
        mock_send.assert_not_called()

    def test_idempotent_against_duplicate_webhook_delivery(self):
        """Stripe delivers at-least-once — a repeat event must not double-send the email."""
        _pending_ticket()
        session = SimpleNamespace(
            id="cs_webhook_1",
            customer_details=SimpleNamespace(email="guest@test.com", name="Guest Buyer"),
        )

        with patch("apps.tickets.email_service.send_ticket_confirmation") as mock_send:
            PaymentCallbackView()._handle_ticket_completed(session, {"type": "ticket_order"})
            PaymentCallbackView()._handle_ticket_completed(session, {"type": "ticket_order"})

        mock_send.assert_called_once()

    def test_unknown_session_id_does_not_raise(self):
        session = SimpleNamespace(
            id="cs_does_not_exist",
            customer_details=SimpleNamespace(email="x@test.com", name="X"),
        )
        PaymentCallbackView()._handle_ticket_completed(session, {"type": "ticket_order"})  # should not raise


class TicketExpiredWebhookTests(BaseAPITestCase):
    def test_expired_session_deletes_the_pending_hold(self):
        _pending_ticket()
        session = SimpleNamespace(id="cs_webhook_1")

        PaymentCallbackView()._handle_ticket_expired(session, {"type": "ticket_order"})

        self.assertFalse(TicketOrder.objects.filter(stripe_session_id="cs_webhook_1").exists())

    def test_does_not_delete_an_already_paid_order(self):
        """Only abandoned (still-PENDING) sessions should ever expire — a paid order
        must never be removed even if Stripe later reports that session as expired."""
        _pending_ticket(status=TicketOrder.Status.PAID)
        session = SimpleNamespace(id="cs_webhook_1")

        PaymentCallbackView()._handle_ticket_expired(session, {"type": "ticket_order"})

        self.assertTrue(TicketOrder.objects.filter(stripe_session_id="cs_webhook_1").exists())


class _FakeStripeMetadata:
    """Mimics stripe._stripe_object.StripeObject (this SDK version): supports
    .to_dict() but has NO .get() — calling metadata.get(...) directly on it
    raises AttributeError. Every prior test in this file built `metadata` as
    a plain Python dict and called the handler methods directly, which never
    exercised PaymentCallbackView.post()'s own metadata handling — that's how
    a real production 500 (every ticket webhook crashing) slipped past the
    suite. This test goes through post() itself with a metadata object shaped
    like the real one, so it would have caught it."""

    def __init__(self, data):
        self._data = dict(data)

    def to_dict(self):
        return dict(self._data)


class WebhookRealMetadataShapeTests(BaseAPITestCase):
    def test_post_does_not_crash_on_stripe_object_style_metadata(self):
        _pending_ticket(session_id="cs_webhook_meta")
        session = SimpleNamespace(
            id="cs_webhook_meta",
            customer_details=SimpleNamespace(email="guest@test.com", name="Guest Buyer"),
            metadata=_FakeStripeMetadata({"type": "ticket_order"}),
        )
        event = {"type": "checkout.session.completed", "data": {"object": session}}

        with patch("apps.payments.views.verify_webhook", return_value=event), \
             patch("apps.tickets.email_service.send_ticket_confirmation"):
            response = self.client.post(
                reverse("payments:callback"),
                data="{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="test",
            )

        self.assert_status(response, status.HTTP_200_OK)
        order = TicketOrder.objects.get(stripe_session_id="cs_webhook_meta")
        self.assertEqual(order.status, TicketOrder.Status.PAID)
