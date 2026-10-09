"""
Tests for the guest ticket confirmation email — specifically that the QR is
sent as a real inline attachment, not a data: URI. Gmail (and most mail
clients) strip data: URI images from HTML email bodies entirely, so an
<img src="data:..."> QR silently renders as a broken image for guests —
this is exactly what shipped and was caught live on staging.
"""
from django.core import mail
from django.test import TestCase

from apps.tickets.email_service import QR_CONTENT_ID, send_ticket_confirmation


class TicketConfirmationEmailTests(TestCase):
    def test_qr_is_sent_as_inline_cid_attachment_not_a_data_uri(self):
        send_ticket_confirmation(
            customer_email="guest@test.com",
            customer_name="Guest Buyer",
            product_name="North Division — Single Match Pass (Week 1)",
            amount_cents=1000,
            qr_png_bytes=b"\x89PNG\r\n\x1a\nfake-png-bytes",
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]

        # The HTML body must reference the attachment by Content-ID, never embed it inline.
        html_body = next(content for content, mimetype in message.alternatives if mimetype == "text/html")
        self.assertIn(f"cid:{QR_CONTENT_ID}", html_body)
        self.assertNotIn("data:image/png;base64,", html_body)

        # The QR must actually be attached as an inline image with that Content-ID.
        image_attachments = [a for a in message.attachments if hasattr(a, "get_content_type")]
        self.assertEqual(len(image_attachments), 1)
        qr_attachment = image_attachments[0]
        self.assertEqual(qr_attachment.get_content_type(), "image/png")
        self.assertEqual(qr_attachment["Content-ID"], f"<{QR_CONTENT_ID}>")
        self.assertEqual(qr_attachment.get_payload(decode=True), b"\x89PNG\r\n\x1a\nfake-png-bytes")

    def test_recipient_and_subject(self):
        send_ticket_confirmation(
            customer_email="guest@test.com",
            customer_name="Guest Buyer",
            product_name="South Division — Supporter Bundle",
            amount_cents=6000,
            qr_png_bytes=b"fake",
        )

        message = mail.outbox[0]
        self.assertEqual(message.to, ["guest@test.com"])
        self.assertIn("South Division — Supporter Bundle", message.subject)
