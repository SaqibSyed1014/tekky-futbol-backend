from django.urls import path

from .views import (
    ApplicationRootView,
    FrontendApproveApplicationView,
    FrontendRejectApplicationView,
    PlayerApplicationListView,
)

app_name = "applications"

urlpatterns = [
    # Root: POST (public registration) or GET (admin list)
    path("", ApplicationRootView.as_view(), name="create"),

    # Player — GET /applications/me/
    path("me/", PlayerApplicationListView.as_view(), name="my_list"),

    # Admin one-click actions — PATCH /applications/<id>/approve|reject
    path("<uuid:pk>/approve/", FrontendApproveApplicationView.as_view(), name="approve"),
    path("<uuid:pk>/reject/",  FrontendRejectApplicationView.as_view(), name="reject"),
]
