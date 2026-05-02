from django.urls import path

from .views import ChangePasswordView, UserMeView

app_name = "users"

urlpatterns = [
    path("me/",              UserMeView.as_view(),       name="me"),
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),
]
