"""Verify Google and Apple ID tokens for fan Sign-In."""

import logging

import jwt
from django.conf import settings
from jwt import PyJWKClient
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)

APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

_apple_jwk_client: PyJWKClient | None = None


def _apple_client() -> PyJWKClient:
    global _apple_jwk_client
    if _apple_jwk_client is None:
        _apple_jwk_client = PyJWKClient(APPLE_KEYS_URL, cache_keys=True)
    return _apple_jwk_client


def verify_google_token(id_token_str: str) -> dict:
    """
    Verify a Google ID token and return {email, name, google_id}.
    """
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or ""
    if not client_id:
        raise AuthenticationFailed("Google Sign-In is not configured.")

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        info = google_id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            client_id,
            clock_skew_in_seconds=10,
        )
    except Exception:
        logger.warning("Google ID token verification failed", exc_info=True)
        raise AuthenticationFailed("Google Sign-In could not be verified. Please try again.")

    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise AuthenticationFailed("Google Sign-In could not be verified. Please try again.")

    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified"):
        raise AuthenticationFailed("Google did not provide a verified email address.")

    return {
        "email": email,
        "name": (info.get("name") or "").strip(),
        "google_id": str(info.get("sub") or ""),
    }


def verify_apple_token(id_token_str: str) -> dict:
    """
    Verify an Apple identity token and return {email, apple_id}.
    Email is present on first authorization; later logins may omit it.
    """
    client_id = getattr(settings, "APPLE_CLIENT_ID", "") or ""
    if not client_id:
        raise AuthenticationFailed("Apple Sign-In is not configured.")

    try:
        signing_key = _apple_client().get_signing_key_from_jwt(id_token_str)
        payload = jwt.decode(
            id_token_str,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=APPLE_ISSUER,
        )
    except Exception:
        logger.warning("Apple ID token verification failed", exc_info=True)
        raise AuthenticationFailed("Apple Sign-In could not be verified. Please try again.")

    apple_id = str(payload.get("sub") or "")
    if not apple_id:
        raise AuthenticationFailed("Apple Sign-In could not be verified. Please try again.")

    email = (payload.get("email") or "").strip().lower()
    return {
        "email": email,
        "apple_id": apple_id,
    }
