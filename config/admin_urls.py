"""
Central admin URL router — all /api/v1/admin/* routes live here.

Keeping admin routing in one file makes it trivial to audit what the
admin surface exposes and to apply rate limiting or middleware at the
reverse-proxy level by matching a single path prefix.
"""
from django.urls import path

from apps.applications.views import AdminApplicationListView, AdminApplicationUpdateView
from apps.users.admin_views import AdminUserListView

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
]
# fmt: on
