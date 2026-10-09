import base64
import uuid

from apps.tickets.services import InvalidTicketToken, make_qr_token, render_qr_base64, verify_qr_token
from apps.users.tests.base import BaseAPITestCase


class QrTokenTests(BaseAPITestCase):
    def test_roundtrip(self):
        ticket_id = uuid.uuid4()
        token = make_qr_token(ticket_id)
        self.assertEqual(verify_qr_token(token), ticket_id)

    def test_tampered_token_is_rejected(self):
        token = make_qr_token(uuid.uuid4())
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with self.assertRaises(InvalidTicketToken):
            verify_qr_token(tampered)

    def test_garbage_token_is_rejected(self):
        with self.assertRaises(InvalidTicketToken):
            verify_qr_token("not-a-real-token")

    def test_token_for_different_ticket_ids_differ(self):
        self.assertNotEqual(make_qr_token(uuid.uuid4()), make_qr_token(uuid.uuid4()))

    def test_render_qr_base64_produces_a_valid_png(self):
        token = make_qr_token(uuid.uuid4())
        encoded = render_qr_base64(token)
        png_bytes = base64.b64decode(encoded)
        self.assertEqual(png_bytes[:8], b"\x89PNG\r\n\x1a\n")  # PNG magic bytes
