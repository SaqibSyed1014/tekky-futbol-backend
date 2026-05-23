from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health_check(request):
    return JsonResponse({"status": "ok"})

API_V1 = "api/v1/"

urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("admin/", admin.site.urls),

    # -------------------------------------------------------------------------
    # Auth  — public + protected identity endpoints
    # POST /api/v1/auth/register/
    # POST /api/v1/auth/login/
    # POST /api/v1/auth/token/refresh/
    # GET  /api/v1/auth/me/
    # -------------------------------------------------------------------------
    path(f"{API_V1}auth/", include("apps.users.auth_urls", namespace="auth")),

    # -------------------------------------------------------------------------
    # Users  — player-facing
    # GET  /api/v1/users/me/
    # -------------------------------------------------------------------------
    path(f"{API_V1}users/", include("apps.users.urls", namespace="users")),

    # -------------------------------------------------------------------------
    # Teams
    # -------------------------------------------------------------------------
    path(f"{API_V1}teams/", include("apps.teams.urls", namespace="teams")),

    # -------------------------------------------------------------------------
    # Applications  — player-facing
    # POST /api/v1/applications/
    # GET  /api/v1/applications/me/
    # -------------------------------------------------------------------------
    path(f"{API_V1}applications/", include("apps.applications.urls", namespace="applications")),

    # -------------------------------------------------------------------------
    # Waivers  — player/captain sign + read own waiver
    # GET  /api/v1/waivers/me/
    # POST /api/v1/waivers/me/
    # -------------------------------------------------------------------------
    path(f"{API_V1}waivers/", include("apps.waivers.urls", namespace="waivers")),

    # -------------------------------------------------------------------------
    # Admin dashboard  — all admin-facing endpoints in one namespace
    # GET   /api/v1/admin/users/
    # GET   /api/v1/admin/applications/
    # PATCH /api/v1/admin/applications/{id}/
    # GET   /api/v1/admin/waivers/signed/
    # GET   /api/v1/admin/waivers/unsigned/
    # -------------------------------------------------------------------------
    path(f"{API_V1}admin/", include(("config.admin_urls", "api_admin"))),
]
