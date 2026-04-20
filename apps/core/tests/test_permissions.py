"""
Unit tests for custom DRF permission classes:
    - IsAdmin
    - IsPlayer
    - IsOwner

These are pure unit tests — they mock the request and view objects so no
HTTP stack or database is involved.  Database is only used for IsOwner tests
where object identity (==) must be real (mock equality is unreliable).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory

from apps.core.permissions import IsAdmin, IsOwner, IsPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str, authenticated: bool = True) -> MagicMock:
    """Return a lightweight mock that satisfies the permission checks."""
    user = MagicMock()
    user.is_authenticated = authenticated
    user.role = role
    return user


_UNSET = object()  # sentinel — distinguishes "no arg" from explicit None


def _make_request(user=_UNSET) -> MagicMock:
    request = MagicMock()
    request.user = _make_user("player") if user is _UNSET else user
    return request


_VIEW = MagicMock()  # permissions never inspect the view directly


# ===========================================================================
# IsAdmin
# ===========================================================================


class IsAdminPermissionTest(SimpleTestCase):

    def setUp(self):
        self.perm = IsAdmin()

    def test_admin_user_is_granted_access(self):
        request = _make_request(_make_user("admin"))
        self.assertTrue(self.perm.has_permission(request, _VIEW))

    def test_player_user_is_denied_access(self):
        request = _make_request(_make_user("player"))
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_unauthenticated_user_is_denied_access(self):
        request = _make_request(_make_user("admin", authenticated=False))
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_anonymous_user_is_denied_access(self):
        """AnonymousUser: is_authenticated=False, no role attribute."""
        anon = MagicMock()
        anon.is_authenticated = False
        request = _make_request(anon)
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_none_user_is_denied_access(self):
        request = _make_request(None)
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_has_permission_returns_bool(self):
        request = _make_request(_make_user("admin"))
        result = self.perm.has_permission(request, _VIEW)
        self.assertIsInstance(result, bool)


# ===========================================================================
# IsPlayer
# ===========================================================================


class IsPlayerPermissionTest(SimpleTestCase):

    def setUp(self):
        self.perm = IsPlayer()

    def test_player_user_is_granted_access(self):
        request = _make_request(_make_user("player"))
        self.assertTrue(self.perm.has_permission(request, _VIEW))

    def test_admin_user_is_denied_access(self):
        request = _make_request(_make_user("admin"))
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_unauthenticated_player_is_denied_access(self):
        request = _make_request(_make_user("player", authenticated=False))
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_anonymous_user_is_denied_access(self):
        anon = MagicMock()
        anon.is_authenticated = False
        request = _make_request(anon)
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_none_user_is_denied_access(self):
        request = _make_request(None)
        self.assertFalse(self.perm.has_permission(request, _VIEW))

    def test_has_permission_returns_bool(self):
        request = _make_request(_make_user("player"))
        result = self.perm.has_permission(request, _VIEW)
        self.assertIsInstance(result, bool)


# ===========================================================================
# IsOwner
# ===========================================================================


class IsOwnerPermissionTest(TestCase):
    """
    IsOwner.has_object_permission — three ownership resolution paths:
        1. obj IS the user  (User model)
        2. obj.user == request.user  (PlayerProfile, FreeAgent)
        3. obj.applicant == request.user  (Application)
    """

    def setUp(self):
        from apps.users.tests.base import BaseAPITestCase, TEST_PASSWORD
        from apps.users.services import UserService

        self.perm = IsOwner()
        self.user_a = UserService.create_user(
            email="owner_a@test.com", password=TEST_PASSWORD, role="player"
        )
        self.user_b = UserService.create_user(
            email="owner_b@test.com", password=TEST_PASSWORD, role="player"
        )

    def _req(self, user):
        r = MagicMock()
        r.user = user
        return r

    # -----------------------------------------------------------------------
    # Case 1: obj == request.user  (User model)
    # -----------------------------------------------------------------------

    def test_user_is_own_object_returns_true(self):
        request = self._req(self.user_a)
        self.assertTrue(
            self.perm.has_object_permission(request, _VIEW, self.user_a)
        )

    def test_user_is_other_user_object_returns_false(self):
        request = self._req(self.user_a)
        self.assertFalse(
            self.perm.has_object_permission(request, _VIEW, self.user_b)
        )

    # -----------------------------------------------------------------------
    # Case 2: obj.user == request.user  (PlayerProfile / FreeAgent)
    # -----------------------------------------------------------------------

    def test_object_with_user_fk_equal_to_request_user_returns_true(self):
        obj = SimpleNamespace(user=self.user_a)
        request = self._req(self.user_a)
        self.assertTrue(
            self.perm.has_object_permission(request, _VIEW, obj)
        )

    def test_object_with_user_fk_different_from_request_user_returns_false(self):
        obj = SimpleNamespace(user=self.user_b)
        request = self._req(self.user_a)
        self.assertFalse(
            self.perm.has_object_permission(request, _VIEW, obj)
        )

    # -----------------------------------------------------------------------
    # Case 3: obj.applicant == request.user  (Application)
    # -----------------------------------------------------------------------

    def test_object_with_applicant_equal_to_request_user_returns_true(self):
        obj = SimpleNamespace(applicant=self.user_a)
        request = self._req(self.user_a)
        self.assertTrue(
            self.perm.has_object_permission(request, _VIEW, obj)
        )

    def test_object_with_applicant_different_from_request_user_returns_false(self):
        obj = SimpleNamespace(applicant=self.user_b)
        request = self._req(self.user_a)
        self.assertFalse(
            self.perm.has_object_permission(request, _VIEW, obj)
        )

    # -----------------------------------------------------------------------
    # Fallback: object has no ownership field
    # -----------------------------------------------------------------------

    def test_object_with_no_ownership_field_returns_false(self):
        obj = SimpleNamespace(name="unrelated object")
        request = self._req(self.user_a)
        self.assertFalse(
            self.perm.has_object_permission(request, _VIEW, obj)
        )

    # -----------------------------------------------------------------------
    # Resolution priority: .user is checked before .applicant
    # -----------------------------------------------------------------------

    def test_user_fk_takes_priority_over_applicant_fk(self):
        """
        If obj has both .user and .applicant, .user is checked first.
        This test verifies the documented priority order.
        """
        # .user matches, .applicant doesn't — should still return True
        obj = SimpleNamespace(user=self.user_a, applicant=self.user_b)
        request = self._req(self.user_a)
        self.assertTrue(
            self.perm.has_object_permission(request, _VIEW, obj)
        )

    def test_user_fk_mismatch_does_not_fall_through_to_applicant(self):
        """
        If .user exists but does not match, .applicant is NOT checked.
        Ownership is strictly .user-first when the attribute exists.
        """
        # .user is present but different; .applicant matches
        obj = SimpleNamespace(user=self.user_b, applicant=self.user_a)
        request = self._req(self.user_a)
        # .user=user_b != user_a → False; should NOT fall through to applicant
        self.assertFalse(
            self.perm.has_object_permission(request, _VIEW, obj)
        )
