from django.urls import path

from .views import WaiverMeView

app_name = "waivers"

urlpatterns = [
    # GET  /api/v1/waivers/me/  — check own waiver status
    # POST /api/v1/waivers/me/  — submit signed waiver
    path("me/", WaiverMeView.as_view(), name="waiver_me"),
]
