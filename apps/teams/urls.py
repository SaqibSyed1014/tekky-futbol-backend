from django.urls import path

# ---------------------------------------------------------------------------
# WAIVER GATE — apply to every view that needs it:
#
#   from apps.waivers.permissions import HasSignedWaiver
#
#   class FreeAgentPoolView(generics.ListAPIView):
#       permission_classes = [IsAuthenticated, HasSignedWaiver]   # ← players must sign
#
#   class CreateInviteView(APIView):
#       permission_classes = [IsAuthenticated, IsCaptain, HasSignedWaiver]  # ← captains too
#
# HasSignedWaiver returns {"error": "waiver_required"} on 403 so the
# frontend can detect and redirect to /user/waiver automatically.
# ---------------------------------------------------------------------------

from .views import (
    DirectInviteView,
    FreeAgentPoolView,
    InviteListView,
    JoinPageView,
    JoinViaLinkView,
    LinkInviteRegisterView,
    LinkInviteView,
    MyRosterView,
    MyTeamView,
    PlayerMembershipView,
    RemovePlayerView,
    RevokeInviteView,
    ValidateLinkInviteView,
)

app_name = "teams"

urlpatterns = [
    # ── Player: own membership + team info ─────────────────────────────
    path("my-membership/",               PlayerMembershipView.as_view(), name="my_membership"),

    # ── Captain: team overview ──────────────────────────────────────────
    path("my/",                          MyTeamView.as_view(),        name="my_team"),

    # ── Captain: roster management ─────────────────────────────────────
    path("my/roster/",                   MyRosterView.as_view(),      name="my_roster"),
    path("my/roster/<uuid:user_id>/",    RemovePlayerView.as_view(),  name="remove_player"),

    # ── Captain: direct invite (registered player) ─────────────────────
    path("my/invites/",                  InviteListView.as_view(),    name="invite_list"),
    path("my/invites/direct/",           DirectInviteView.as_view(),  name="direct_invite"),
    path("my/invites/link/",             LinkInviteView.as_view(),    name="link_invite"),
    path("my/invites/<uuid:invite_id>/", RevokeInviteView.as_view(),  name="revoke_invite"),

    # ── Captain: free-agent pool ────────────────────────────────────────
    path("free-agents/",                 FreeAgentPoolView.as_view(), name="free_agents"),

    # ── Public: join page (registered player) ──────────────────────────
    path("join/<uuid:token>/",           JoinPageView.as_view(),      name="join_page"),

    # ── Public: validate link invite (before registration) ─────────────
    path("join-link/<uuid:token>/validate/", ValidateLinkInviteView.as_view(), name="validate_link_invite"),

    # ── Public: register + join in one shot (non-registered user) ──────
    path("join-link/<uuid:token>/register/", LinkInviteRegisterView.as_view(), name="join_link_register"),

    # ── Public: join via link (non-registered, after signup) ───────────
    path("join-link/<uuid:token>/",      JoinViaLinkView.as_view(),   name="join_via_link"),
]
