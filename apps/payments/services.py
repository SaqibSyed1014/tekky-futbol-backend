"""
Bank of America Hosted Payments Page (HPP) integration.

Uses the CyberSource Secure Acceptance protocol that BoA Gateway is built on:
  1. Backend builds a dict of signed fields + HMAC-SHA256 signature.
  2. Frontend auto-POSTs those fields to the BoA HPP URL.
  3. Customer fills card details on BoA's page.
  4. BoA POSTs result to our callback URL (server-to-server).
  5. BoA redirects browser to our success / cancel URL.

Credential mapping (from what the bank provided):
  BOA_ACCESS_KEY  → "Key"
  BOA_SECRET_KEY  → "Secret Key"
  BOA_MERCHANT_ID → "Merchant ID"
  BOA_PROFILE_ID  → defaults to BOA_ACCESS_KEY (UUID format matches profile_id)
"""

import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timezone

from django.conf import settings


# ── HPP endpoint ──────────────────────────────────────────────────────────────
HPP_TEST_URL = "https://testsecureacceptance.merchant-services.bankofamerica.com/pay"
HPP_PROD_URL = "https://secureacceptance.merchant-services.bankofamerica.com/pay"


def _get_hpp_url():
    return HPP_TEST_URL if getattr(settings, "BOA_TEST_MODE", True) else HPP_PROD_URL


def _sign(params: dict, secret_key: str) -> str:
    """HMAC-SHA256 over 'key=value,key=value,...' ordered by signed_field_names."""
    keys = params["signed_field_names"].split(",")
    signing_string = ",".join(f"{k}={params[k]}" for k in keys)
    digest = hmac.new(
        secret_key.encode("utf-8"),
        signing_string.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_hpp_form(reference_number: str, amount: str = "700.00") -> dict:
    """
    Build the signed form fields to POST to the BoA HPP.
    Returns a dict with all fields + 'hpp_url' for the form action.
    """
    access_key  = settings.BOA_ACCESS_KEY
    profile_id  = getattr(settings, "BOA_PROFILE_ID", access_key)
    secret_key  = settings.BOA_SECRET_KEY
    frontend    = settings.FRONTEND_BASE_URL
    backend     = settings.BACKEND_BASE_URL

    signed_date_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    transaction_uuid = str(uuid.uuid4())

    signed_fields = [
        "access_key",
        "profile_id",
        "transaction_uuid",
        "signed_field_names",
        "unsigned_field_names",
        "signed_date_time",
        "locale",
        "transaction_type",
        "reference_number",
        "amount",
        "currency",
        "override_custom_receipt_page",
        "override_custom_cancel_page",
        "override_backoffice_post_url",
    ]

    params = {
        "access_key":                    access_key,
        "profile_id":                    profile_id,
        "transaction_uuid":              transaction_uuid,
        "signed_field_names":            ",".join(signed_fields),
        "unsigned_field_names":          "",
        "signed_date_time":              signed_date_time,
        "locale":                        "en-us",
        "transaction_type":              "sale",
        "reference_number":              reference_number,
        "amount":                        amount,
        "currency":                      "USD",
        "override_custom_receipt_page":  f"{frontend}/payment/success",
        "override_custom_cancel_page":   f"{frontend}/payment/failed",
        "override_backoffice_post_url":  f"{backend}/api/v1/payments/callback/",
    }

    params["signature"] = _sign(params, secret_key)

    return {
        **params,
        "hpp_url": _get_hpp_url(),
    }


def verify_callback(post_data: dict) -> bool:
    """
    Verify the HMAC-SHA256 signature on BoA's callback POST.
    Returns True if the signature is valid, False otherwise.
    """
    secret_key = settings.BOA_SECRET_KEY
    received_sig = post_data.get("signature", "")

    signed_field_names = post_data.get("signed_field_names", "")
    if not signed_field_names:
        return False

    keys = signed_field_names.split(",")
    signing_string = ",".join(f"{k}={post_data.get(k, '')}" for k in keys)
    expected = hmac.new(
        secret_key.encode("utf-8"),
        signing_string.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(expected).decode("utf-8")

    return hmac.compare_digest(received_sig, expected_b64)
