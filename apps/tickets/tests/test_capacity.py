"""
Tests for the capacity/sold-out logic in apps/tickets/services.py — the
part of this feature most likely to cause real-world harm if wrong
(overselling a capped, non-refundable pass).
"""
from django.db import transaction

from apps.tickets.models import TicketOrder
from apps.tickets.services import SoldOut, remaining_bundle_capacity, remaining_capacity, reserve_capacity
from apps.users.tests.base import BaseAPITestCase


def _make_ticket(tier, division="", week_number=None, status=TicketOrder.Status.PAID):
    return TicketOrder.objects.create(
        stripe_session_id=f"sess_{TicketOrder.objects.count()}_{tier}_{division}_{week_number}_{status}",
        tier=tier,
        division=division,
        week_number=week_number,
        product_name="Test Pass",
        amount_cents=1000,
        status=status,
    )


class MatchdayCapacityTests(BaseAPITestCase):
    def test_single_match_reserves_until_cap_then_sells_out(self):
        for _ in range(40):
            _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="north", week_number=1)

        self.assertEqual(remaining_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 1), 0)
        with self.assertRaises(SoldOut):
            with transaction.atomic():
                reserve_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 1)

    def test_pending_orders_count_against_the_cap(self):
        """A buyer mid-checkout must occupy their slot — otherwise two people could both pay for the last spot."""
        for _ in range(40):
            _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="north", week_number=2, status=TicketOrder.Status.PENDING)

        with self.assertRaises(SoldOut):
            with transaction.atomic():
                reserve_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 2)

    def test_different_week_has_independent_capacity(self):
        for _ in range(40):
            _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="north", week_number=3)

        # Week 4 is untouched — should still have full capacity.
        self.assertEqual(remaining_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 4), 40)
        with transaction.atomic():
            reserve_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 4)  # should not raise

    def test_different_division_has_independent_capacity(self):
        for _ in range(40):
            _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="north", week_number=5)

        self.assertEqual(remaining_capacity(TicketOrder.Tier.SINGLE_MATCH, "south", 5), 40)

    def test_bundle_and_single_share_the_same_40_pool(self):
        for _ in range(30):
            _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="south", week_number=1)
        for _ in range(10):
            _make_ticket(TicketOrder.Tier.SUPPORTER_BUNDLE, division="south", week_number=1)

        # Pool is full (30 + 10 = 40) even though bundle's own sub-cap (10) isn't separately exceeded.
        with self.assertRaises(SoldOut):
            with transaction.atomic():
                reserve_capacity(TicketOrder.Tier.SINGLE_MATCH, "south", 1)

    def test_bundle_sub_cap_enforced_independently_of_matchday_cap(self):
        """10 bundles sold (well under the shared 40) should still block an 11th bundle,
        while a Single Match Pass for the same matchday remains purchasable."""
        for _ in range(10):
            _make_ticket(TicketOrder.Tier.SUPPORTER_BUNDLE, division="north", week_number=6)

        self.assertEqual(remaining_bundle_capacity("north", 6), 0)
        with self.assertRaises(SoldOut):
            with transaction.atomic():
                reserve_capacity(TicketOrder.Tier.SUPPORTER_BUNDLE, "north", 6)

        # Single Match Pass is a separate concern — only the shared 40 applies to it.
        with transaction.atomic():
            reserve_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 6)  # should not raise

    def test_checked_in_orders_still_count_as_occupying_a_slot(self):
        """A checked-in ticket was still a paid sale — it must keep counting against the cap."""
        for _ in range(39):
            _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="north", week_number=7)
        _make_ticket(TicketOrder.Tier.SINGLE_MATCH, division="north", week_number=7, status=TicketOrder.Status.CHECKED_IN)

        self.assertEqual(remaining_capacity(TicketOrder.Tier.SINGLE_MATCH, "north", 7), 0)


class LeagueWideCapacityTests(BaseAPITestCase):
    def test_season_pass_sells_out_at_20(self):
        for _ in range(20):
            _make_ticket(TicketOrder.Tier.SEASON_PASS)

        self.assertEqual(remaining_capacity(TicketOrder.Tier.SEASON_PASS), 0)
        with self.assertRaises(SoldOut):
            with transaction.atomic():
                reserve_capacity(TicketOrder.Tier.SEASON_PASS)

    def test_playoff_pass_sells_out_at_60(self):
        for _ in range(60):
            _make_ticket(TicketOrder.Tier.PLAYOFF_PASS)

        with self.assertRaises(SoldOut):
            with transaction.atomic():
                reserve_capacity(TicketOrder.Tier.PLAYOFF_PASS)

    def test_season_and_playoff_caps_are_independent(self):
        for _ in range(20):
            _make_ticket(TicketOrder.Tier.SEASON_PASS)

        self.assertEqual(remaining_capacity(TicketOrder.Tier.PLAYOFF_PASS), 60)
