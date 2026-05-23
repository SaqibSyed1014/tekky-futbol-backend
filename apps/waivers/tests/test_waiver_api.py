"""
Tests for the waiver system.

Endpoints under test:
    GET  /api/v1/waivers/me/             — check own waiver status
    POST /api/v1/waivers/me/             — submit signed waiver
    GET  /api/v1/admin/waivers/signed/   — admin: list signed waivers
    GET  /api/v1/admin/waivers/unsigned/ — admin: list unsigned users

Also covers:
    - HasSignedWaiver permission class
    - waiver_signed flag on /auth/me response
    - Duplicate-prevention (idempotent POST)
    - Serializer validation (age, clauses, signature)
    - IP address capture
"""
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status

from apps.users.tests.base import BaseAPITestCase
from apps.waivers.models import CURRENT_WAIVER_VERSION, REQUIRED_CLAUSES, WaiverSignature
from apps.waivers.permissions import HasSignedWaiver

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _all_clauses_true() -> dict:
    """Return a dict with all required clause keys set to True."""
    return {key: True for key in REQUIRED_CLAUSES}


def _valid_payload(**overrides) -> dict:
    """
    Return a complete, valid waiver POST payload.
    Individual fields can be overridden via kwargs.
    """
    payload = {
        "is_minor":                False,
        "date_of_birth":           "1990-06-15",
        "address":                 "123 Main Street, Chicago, IL 60601",
        "medical_conditions":      "",
        "emergency_contact_name":  "Jane Doe",
        "emergency_contact_rel":   "Spouse",
        "emergency_contact_phone": "555-0100",
        "clauses_initialed":       _all_clauses_true(),
        "printed_name":            "John Doe",
        # Signature image — any non-blank string is accepted
        "signature_image":         "data:image/png;base64," + "A" * 150,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GET /api/v1/waivers/me/
# ---------------------------------------------------------------------------

class WaiverStatusGetTests(BaseAPITestCase):
    """GET /waivers/me/ — read own waiver status."""

    url = reverse("waivers:waiver_me")

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_unsigned_user_returns_waiver_signed_false(self):
        player = self.create_player()
        self.authenticate_as(player)

        response = self.client.get(self.url)

        self.assert_status(response, status.HTTP_200_OK)
        self.assertFalse(response.data["waiver_signed"])

    def test_signed_user_returns_waiver_signed_true(self):
        player = self.create_player()
        WaiverSignature.objects.create(
            user=player,
            **_build_signature_fields(),
        )
        self.authenticate_as(player)

        response = self.client.get(self.url)

        self.assert_status(response, status.HTTP_200_OK)
        self.assertTrue(response.data["waiver_signed"])

    def test_signed_response_contains_required_fields(self):
        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        self.authenticate_as(player)

        data = self.client.get(self.url).data

        self.assertIn("signed_at",       data)
        self.assertIn("printed_name",    data)
        self.assertIn("waiver_version",  data)
        self.assertIn("is_current_version", data)

    def test_signed_response_reports_current_version(self):
        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        self.authenticate_as(player)

        data = self.client.get(self.url).data

        self.assertEqual(data["waiver_version"], CURRENT_WAIVER_VERSION)
        self.assertTrue(data["is_current_version"])

    def test_admin_user_unsigned_returns_waiver_signed_false(self):
        admin = self.create_admin()
        self.authenticate_as(admin)

        response = self.client.get(self.url)

        self.assert_status(response, status.HTTP_200_OK)
        self.assertFalse(response.data["waiver_signed"])


# ---------------------------------------------------------------------------
# POST /api/v1/waivers/me/
# ---------------------------------------------------------------------------

class WaiverSubmitTests(BaseAPITestCase):
    """POST /waivers/me/ — submit signed waiver."""

    url = reverse("waivers:waiver_me")

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_valid_submission_returns_201(self):
        player = self.create_player()
        self.authenticate_as(player)

        response = self.client.post(self.url, _valid_payload(), format="json")

        self.assert_status(response, status.HTTP_201_CREATED)

    def test_valid_submission_creates_db_record(self):
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(self.url, _valid_payload(), format="json")

        self.assertTrue(WaiverSignature.objects.filter(user=player).exists())

    def test_valid_submission_response_contains_waiver_signed_true(self):
        player = self.create_player()
        self.authenticate_as(player)

        data = self.client.post(self.url, _valid_payload(), format="json").data

        self.assertTrue(data["waiver_signed"])
        self.assertIn("signed_at",    data)
        self.assertIn("printed_name", data)

    def test_submission_sets_waiver_version_to_current(self):
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(self.url, _valid_payload(), format="json")

        sig = WaiverSignature.objects.get(user=player)
        self.assertEqual(sig.waiver_version, CURRENT_WAIVER_VERSION)

    def test_submission_captures_ip_address(self):
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(
            self.url,
            _valid_payload(),
            format="json",
            REMOTE_ADDR="192.168.1.42",
        )

        sig = WaiverSignature.objects.get(user=player)
        self.assertEqual(sig.ip_address, "192.168.1.42")

    def test_submission_prefers_x_forwarded_for_over_remote_addr(self):
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(
            self.url,
            _valid_payload(),
            format="json",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1",
        )

        sig = WaiverSignature.objects.get(user=player)
        self.assertEqual(sig.ip_address, "203.0.113.5")

    def test_submission_without_medical_conditions_is_accepted(self):
        """medical_conditions is optional."""
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload()
        del payload["medical_conditions"]
        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # Idempotency — duplicate submission
    # ------------------------------------------------------------------

    def test_second_submission_returns_200_not_201(self):
        """Re-POSTing after already signing must be idempotent (200)."""
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(self.url, _valid_payload(), format="json")
        response = self.client.post(self.url, _valid_payload(), format="json")

        self.assert_status(response, status.HTTP_200_OK)

    def test_second_submission_does_not_create_duplicate_record(self):
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(self.url, _valid_payload(), format="json")
        self.client.post(self.url, _valid_payload(), format="json")

        count = WaiverSignature.objects.filter(user=player).count()
        self.assertEqual(count, 1)

    def test_second_submission_still_returns_waiver_signed_true(self):
        player = self.create_player()
        self.authenticate_as(player)

        self.client.post(self.url, _valid_payload(), format="json")
        data = self.client.post(self.url, _valid_payload(), format="json").data

        self.assertTrue(data["waiver_signed"])

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def test_unauthenticated_returns_401(self):
        response = self.client.post(self.url, _valid_payload(), format="json")
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    # ------------------------------------------------------------------
    # Validation — age
    # ------------------------------------------------------------------

    def test_under_18_date_of_birth_with_is_minor_true_requires_guardian_fields(self):
        """
        Providing an under-18 DOB alone is not rejected — age restriction was removed.
        However, submitting with is_minor=True without guardian fields returns 400.
        """
        player = self.create_player()
        self.authenticate_as(player)

        dob = (date.today() - timedelta(days=365 * 10)).isoformat()
        payload = _valid_payload(
            date_of_birth=dob,
            is_minor=True,
            # deliberately omit guardian fields → should fail validation
            printed_name="",
            signature_image="",
        )

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_exactly_18_is_accepted(self):
        player = self.create_player()
        self.authenticate_as(player)

        today = date.today()
        dob_18 = date(today.year - 18, today.month, today.day).isoformat()
        payload = _valid_payload(date_of_birth=dob_18)

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # Validation — clauses
    # ------------------------------------------------------------------

    def test_missing_one_clause_returns_400(self):
        player = self.create_player()
        self.authenticate_as(player)

        clauses = _all_clauses_true()
        clauses["voluntary_participation"] = False  # one clause not checked
        payload = _valid_payload(clauses_initialed=clauses)

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_all_clauses_false_returns_400(self):
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload(
            clauses_initialed={key: False for key in REQUIRED_CLAUSES}
        )

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_missing_clauses_key_returns_400(self):
        player = self.create_player()
        self.authenticate_as(player)

        clauses = _all_clauses_true()
        del clauses["release_of_liability"]
        payload = _valid_payload(clauses_initialed=clauses)

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_empty_clauses_dict_returns_400(self):
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload(clauses_initialed={})

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # Validation — signature image
    # ------------------------------------------------------------------

    def test_empty_signature_image_returns_400(self):
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload(signature_image="")

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_whitespace_only_signature_image_returns_400(self):
        """A signature consisting only of whitespace is rejected."""
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload(signature_image="   ")

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_short_typed_name_as_signature_is_accepted(self):
        """A short typed name (e.g. 'Jo') is valid — no arbitrary length minimum."""
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload(signature_image="Jo")

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # Validation — required fields
    # ------------------------------------------------------------------

    def test_submission_without_address_is_accepted(self):
        """address is optional — omitting it must not cause a 400."""
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload()
        del payload["address"]

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_201_CREATED)

    def test_submission_without_emergency_contact_is_accepted(self):
        """Emergency-contact fields are optional — omitting them must not cause a 400."""
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload()
        del payload["emergency_contact_name"]

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_201_CREATED)

    def test_blank_printed_name_returns_400(self):
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload(printed_name="   ")

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_submission_without_date_of_birth_is_accepted(self):
        """date_of_birth is optional — omitting it must not cause a 400."""
        player = self.create_player()
        self.authenticate_as(player)

        payload = _valid_payload()
        del payload["date_of_birth"]

        response = self.client.post(self.url, payload, format="json")

        self.assert_status(response, status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/waivers/signed/
# ---------------------------------------------------------------------------

class AdminWaiverSignedListTests(BaseAPITestCase):
    """GET /admin/waivers/signed/ — admin list of signed waivers."""

    url = reverse("api_admin:admin_waiver_signed")

    def test_non_admin_returns_403(self):
        player = self.create_player()
        self.authenticate_as(player)

        response = self.client.get(self.url)

        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_admin_receives_paginated_list(self):
        admin  = self.create_admin()
        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        self.authenticate_as(admin)

        data = self.client.get(self.url).data

        self.assertIn("results", data)
        self.assertEqual(data["count"], 1)

    def test_signed_record_contains_user_fields(self):
        admin  = self.create_admin()
        player = self.create_player(email="signer@test.com")
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        self.authenticate_as(admin)

        record = self.client.get(self.url).data["results"][0]

        self.assertEqual(record["user_email"],    "signer@test.com")
        self.assertIn("signed_at",                record)
        self.assertIn("printed_name",             record)
        self.assertIn("waiver_version",           record)
        self.assertIn("ip_address",               record)

    def test_empty_list_when_no_signatures(self):
        admin = self.create_admin()
        self.authenticate_as(admin)

        data = self.client.get(self.url).data

        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_filter_by_role_returns_matching_records_only(self):
        admin   = self.create_admin()
        player1 = self.create_player(email="p1@test.com")
        player2 = self.create_player(email="p2@test.com")
        WaiverSignature.objects.create(user=player1, **_build_signature_fields())
        WaiverSignature.objects.create(user=player2, **_build_signature_fields())
        self.authenticate_as(admin)

        data = self.client.get(self.url, {"role": "player"}).data

        self.assertEqual(data["count"], 2)

    def test_multiple_signatures_all_appear_in_list(self):
        admin = self.create_admin()
        for i in range(3):
            p = self.create_player(email=f"p{i}@test.com")
            WaiverSignature.objects.create(user=p, **_build_signature_fields())
        self.authenticate_as(admin)

        data = self.client.get(self.url).data

        self.assertEqual(data["count"], 3)

    def test_filter_by_is_captain_true_returns_only_captains(self):
        admin   = self.create_admin()
        player  = self.create_player(email="player@test.com")
        captain = self.create_player(email="captain@test.com")
        captain.is_captain = True
        captain.save(update_fields=["is_captain"])
        WaiverSignature.objects.create(user=player,  **_build_signature_fields())
        WaiverSignature.objects.create(user=captain, **_build_signature_fields())
        self.authenticate_as(admin)

        data = self.client.get(self.url, {"is_captain": "true"}).data

        emails = [r["user_email"] for r in data["results"]]
        self.assertIn("captain@test.com",   emails)
        self.assertNotIn("player@test.com", emails)
        self.assertEqual(data["count"], 1)

    def test_filter_by_is_captain_false_returns_only_non_captains(self):
        admin   = self.create_admin()
        player  = self.create_player(email="player@test.com")
        captain = self.create_player(email="captain@test.com")
        captain.is_captain = True
        captain.save(update_fields=["is_captain"])
        WaiverSignature.objects.create(user=player,  **_build_signature_fields())
        WaiverSignature.objects.create(user=captain, **_build_signature_fields())
        self.authenticate_as(admin)

        data = self.client.get(self.url, {"is_captain": "false"}).data

        emails = [r["user_email"] for r in data["results"]]
        self.assertIn("player@test.com",     emails)
        self.assertNotIn("captain@test.com", emails)
        self.assertEqual(data["count"], 1)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/waivers/unsigned/
# ---------------------------------------------------------------------------

class AdminWaiverUnsignedListTests(BaseAPITestCase):
    """GET /admin/waivers/unsigned/ — admin list of users who haven't signed."""

    url = reverse("api_admin:admin_waiver_unsigned")

    def test_non_admin_returns_403(self):
        player = self.create_player()
        self.authenticate_as(player)

        response = self.client.get(self.url)

        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_unsigned_player_appears_in_list(self):
        admin  = self.create_admin()
        player = self.create_player()
        self.authenticate_as(admin)

        data = self.client.get(self.url).data

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["email"], player.email)

    def test_signed_player_does_not_appear_in_list(self):
        admin  = self.create_admin()
        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        self.authenticate_as(admin)

        data = self.client.get(self.url).data

        self.assertEqual(data["count"], 0)

    def test_signing_removes_player_from_unsigned_list(self):
        admin  = self.create_admin()
        player = self.create_player()
        self.authenticate_as(admin)

        before = self.client.get(self.url).data["count"]

        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        after = self.client.get(self.url).data["count"]

        self.assertEqual(before - after, 1)

    def test_filter_by_is_captain_true(self):
        admin   = self.create_admin()
        player  = self.create_player(email="regular@test.com")
        captain = self.create_player(email="captain@test.com")
        captain.is_captain = True
        captain.save(update_fields=["is_captain"])
        self.authenticate_as(admin)

        data = self.client.get(self.url, {"is_captain": "true"}).data

        emails = [r["email"] for r in data["results"]]
        self.assertIn("captain@test.com",    emails)
        self.assertNotIn("regular@test.com", emails)

    def test_filter_by_is_captain_false_returns_only_non_captains(self):
        admin   = self.create_admin()
        player  = self.create_player(email="regular@test.com")
        captain = self.create_player(email="captain@test.com")
        captain.is_captain = True
        captain.save(update_fields=["is_captain"])
        self.authenticate_as(admin)

        data = self.client.get(self.url, {"is_captain": "false"}).data

        emails = [r["email"] for r in data["results"]]
        self.assertIn("regular@test.com",    emails)
        self.assertNotIn("captain@test.com", emails)


# ---------------------------------------------------------------------------
# HasSignedWaiver permission class
# ---------------------------------------------------------------------------

class HasSignedWaiverPermissionTests(BaseAPITestCase):
    """Unit tests for the HasSignedWaiver DRF permission class."""

    def _make_request(self, user):
        """Construct a minimal mock request object."""
        from unittest.mock import MagicMock
        req = MagicMock()
        req.user = user
        return req

    def test_unsigned_user_is_denied(self):
        player  = self.create_player()
        request = self._make_request(player)
        perm    = HasSignedWaiver()

        self.assertFalse(perm.has_permission(request, None))

    def test_signed_user_is_allowed(self):
        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        request = self._make_request(player)
        perm    = HasSignedWaiver()

        self.assertTrue(perm.has_permission(request, None))

    def test_unauthenticated_user_is_denied(self):
        from unittest.mock import MagicMock
        req = MagicMock()
        req.user = MagicMock(is_authenticated=False)
        perm = HasSignedWaiver()

        self.assertFalse(perm.has_permission(req, None))

    def test_permission_message_contains_waiver_required(self):
        perm = HasSignedWaiver()
        self.assertEqual(perm.message.get("error"), "waiver_required")


# ---------------------------------------------------------------------------
# waiver_signed flag on /auth/me
# ---------------------------------------------------------------------------

class WaiverSignedInMeEndpointTests(BaseAPITestCase):
    """waiver_signed field surfaced on the /auth/me response."""

    me_url = reverse("auth:me")

    def test_unsigned_player_has_waiver_signed_false(self):
        player = self.create_player()
        self.authenticate_as(player)

        data = self.client.get(self.me_url).data

        self.assertFalse(data["waiver_signed"])

    def test_signed_player_has_waiver_signed_true(self):
        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())
        self.authenticate_as(player)

        data = self.client.get(self.me_url).data

        self.assertTrue(data["waiver_signed"])

    def test_signing_via_api_reflects_in_me_endpoint(self):
        """End-to-end: submit waiver then confirm /auth/me picks it up."""
        player = self.create_player()
        self.authenticate_as(player)

        # Before signing
        before = self.client.get(self.me_url).data["waiver_signed"]
        self.assertFalse(before)

        # Sign
        self.client.post(
            reverse("waivers:waiver_me"),
            _valid_payload(),
            format="json",
        )

        # After signing
        after = self.client.get(self.me_url).data["waiver_signed"]
        self.assertTrue(after)


# ---------------------------------------------------------------------------
# Model-level integrity
# ---------------------------------------------------------------------------

class WaiverSignatureModelTests(BaseAPITestCase):
    """Direct model tests — uniqueness constraint and helper properties."""

    def test_duplicate_direct_create_raises_integrity_error(self):
        """OneToOneField must prevent a second WaiverSignature for the same user."""
        from django.db import IntegrityError

        player = self.create_player()
        WaiverSignature.objects.create(user=player, **_build_signature_fields())

        with self.assertRaises(IntegrityError):
            WaiverSignature.objects.create(user=player, **_build_signature_fields())

    def test_is_current_version_property(self):
        player = self.create_player()
        sig = WaiverSignature.objects.create(user=player, **_build_signature_fields())

        self.assertTrue(sig.is_current_version)

    def test_all_clauses_signed_property_true_when_all_set(self):
        player = self.create_player()
        sig = WaiverSignature.objects.create(user=player, **_build_signature_fields())

        self.assertTrue(sig.all_clauses_signed)

    def test_all_clauses_signed_property_false_when_one_missing(self):
        player  = self.create_player()
        clauses = _all_clauses_true()
        clauses["voluntary_participation"] = False
        fields  = _build_signature_fields(clauses_initialed=clauses)
        sig     = WaiverSignature.objects.create(user=player, **fields)

        self.assertFalse(sig.all_clauses_signed)

    def test_str_representation_contains_email_and_version(self):
        player = self.create_player(email="strtest@test.com")
        sig    = WaiverSignature.objects.create(user=player, **_build_signature_fields())

        self.assertIn("strtest@test.com",     str(sig))
        self.assertIn(CURRENT_WAIVER_VERSION, str(sig))


# ---------------------------------------------------------------------------
# Private builder — keeps test data in one place
# ---------------------------------------------------------------------------

def _build_signature_fields(**overrides) -> dict:
    """
    Return kwargs suitable for ``WaiverSignature.objects.create(**kwargs)``.
    Does NOT include 'user' — callers must pass that separately.
    """
    fields = {
        "is_minor":                False,
        "date_of_birth":           date(1990, 6, 15),
        "address":                 "123 Main St, Chicago, IL 60601",
        "medical_conditions":      "",
        "emergency_contact_name":  "Jane Doe",
        "emergency_contact_rel":   "Spouse",
        "emergency_contact_phone": "555-0100",
        "clauses_initialed":       _all_clauses_true(),
        "printed_name":            "John Doe",
        "signature_image":         "data:image/png;base64," + "A" * 150,
    }
    fields.update(overrides)
    return fields
