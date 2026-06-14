from django.urls import path

from .views import (
    ChangePasswordView,
    DeleteAccountView,
    UpdatePlayerProfileView,
    UpdateUserView,
    UserMeView,
)
from .profile_views import ProfileLinkView, TeamLinkView

app_name = "users"

urlpatterns = [
    path("me/",                  UserMeView.as_view(),              name="me"),
    path("me/update/",           UpdateUserView.as_view(),          name="update_user"),
    path("me/delete/",           DeleteAccountView.as_view(),       name="delete_account"),
    path("profile/me/",          UpdatePlayerProfileView.as_view(), name="update_profile"),
    path("profile/me/link/",     ProfileLinkView.as_view(),         name="profile_link"),
    path("change-password/",     ChangePasswordView.as_view(),      name="change_password"),
    # Captain: submit team link
    path("team/link/",           TeamLinkView.as_view(),            name="team_link"),
]
