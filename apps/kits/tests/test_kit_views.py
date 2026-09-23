"""
Tests for MyKitView — specifically that it surfaces the captain's
preferred_division so the frontend can filter the kit picker to just
that division's designs — and for the public KitStatusView.
"""
from django.urls import reverse
from rest_framework import status

from apps.users.tests.base import BaseAPITestCase


class MyKitViewPreferredDivisionTests(BaseAPITestCase):
    url = reverse("kits:my_kit")

    def test_reports_captains_preferred_division(self):
        captain = self.create_player(email="captain@test.com")
        captain.profile.preferred_division = "north"
        captain.profile.save(update_fields=["preferred_division"])
        self.create_team(captain, name="North Team FC")

        self.authenticate_as(captain)
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["preferred_division"], "north")

    def test_teammate_also_sees_captains_preferred_division(self):
        captain = self.create_player(email="captain2@test.com")
        captain.profile.preferred_division = "south"
        captain.profile.save(update_fields=["preferred_division"])
        team = self.create_team(captain, name="South Team FC")

        teammate = self.create_player(email="teammate@test.com")
        teammate.profile.team = team
        teammate.profile.save(update_fields=["team"])
        from apps.teams.models import TeamMembership
        TeamMembership.objects.create(user=teammate, team=team, status=TeamMembership.Status.APPROVED)

        self.authenticate_as(teammate)
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["preferred_division"], "south")

    def test_blank_when_captain_has_no_preferred_division(self):
        captain = self.create_player(email="captain3@test.com")
        self.create_team(captain, name="No Division FC")

        self.authenticate_as(captain)
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["preferred_division"], "")


class KitStatusViewTests(BaseAPITestCase):
    url = reverse("kits:kit_status")

    def test_public_no_auth_required(self):
        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["claimed"], [])

    def test_lists_only_locked_selections(self):
        from apps.kits.models import TeamKitSelection

        locked_captain = self.create_player(email="locked-captain@test.com")
        locked_team = self.create_team(locked_captain, name="Locked Team FC")
        TeamKitSelection.objects.create(team=locked_team, kit_slug="north-1", is_locked=True)

        unlocked_captain = self.create_player(email="unlocked-captain@test.com")
        unlocked_team = self.create_team(unlocked_captain, name="Unlocked Team FC")
        TeamKitSelection.objects.create(team=unlocked_team, kit_slug="south-2", is_locked=False)

        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["claimed"], ["north-1"])

    def test_deduplicates_same_slug_locked_by_multiple_teams(self):
        # kit_slug has no DB-level uniqueness constraint across teams, so two
        # teams can (incorrectly) end up with the same slug locked. The public
        # status list should still report it only once.
        from apps.kits.models import TeamKitSelection

        captain_a = self.create_player(email="dup-captain-a@test.com")
        team_a = self.create_team(captain_a, name="Dup Team A FC")
        TeamKitSelection.objects.create(team=team_a, kit_slug="north-5", is_locked=True)

        captain_b = self.create_player(email="dup-captain-b@test.com")
        team_b = self.create_team(captain_b, name="Dup Team B FC")
        TeamKitSelection.objects.create(team=team_b, kit_slug="north-5", is_locked=True)

        response = self.client.get(self.url)
        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(response.data["claimed"], ["north-5"])
