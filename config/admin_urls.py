"""
Central admin URL router — all /api/v1/admin/* routes live here.

Keeping admin routing in one file makes it trivial to audit what the
admin surface exposes and to apply rate limiting or middleware at the
reverse-proxy level by matching a single path prefix.
"""
from django.urls import path

from apps.applications.views import AdminApplicationListView, AdminApplicationUpdateView
from apps.teams.views import AdminMembershipActionView, AdminMembershipListView, AdminTeamListView
from apps.users.admin_views import AdminUserListView
from apps.waivers.views import AdminWaiverSignedListView, AdminWaiverUnsignedListView

# fmt: off
urlpatterns = [
    # ------------------------------------------------------------------
    # Users
    # GET  /api/v1/admin/users/
    # ------------------------------------------------------------------
    path("users/",                          AdminUserListView.as_view(),           name="admin_user_list"),

    # ------------------------------------------------------------------
    # Applications
    # GET   /api/v1/admin/applications/
    # PATCH /api/v1/admin/applications/{id}/
    # ------------------------------------------------------------------
    path("applications/",                   AdminApplicationListView.as_view(),    name="admin_application_list"),
    path("applications/<uuid:pk>/",         AdminApplicationUpdateView.as_view(),  name="admin_application_detail"),

    # ------------------------------------------------------------------
    # Team Memberships
    # GET  /api/v1/admin/memberships/              — list pending/approved
    # POST /api/v1/admin/memberships/{id}/         — approve or reject
    # ------------------------------------------------------------------
    path("memberships/",                    AdminMembershipListView.as_view(),     name="admin_membership_list"),
    path("memberships/<uuid:membership_id>/", AdminMembershipActionView.as_view(), name="admin_membership_action"),

    # ------------------------------------------------------------------
    # Teams
    # GET  /api/v1/admin/teams/   — list all teams with roster counts
    # ------------------------------------------------------------------
    path("teams/",                          AdminTeamListView.as_view(),           name="admin_team_list"),

    # ------------------------------------------------------------------
    # Waivers
    # GET /api/v1/admin/waivers/signed/
    # GET /api/v1/admin/waivers/unsigned/
    # ------------------------------------------------------------------
    path("waivers/signed/",                 AdminWaiverSignedListView.as_view(),   name="admin_waiver_signed"),
    path("waivers/unsigned/",               AdminWaiverUnsignedListView.as_view(), name="admin_waiver_unsigned"),
]
# fmt: on
