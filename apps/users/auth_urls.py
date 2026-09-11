from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AppleOAuthView,
    FanLoginView,
    FanRegisterView,
    ForgotPasswordView,
    GoogleOAuthView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    ResetPasswordView,
)

app_name = "auth"

urlpatterns = [
    # Public
    path("register/",        RegisterView.as_view(),       name="register"),
    path("login/",           LoginView.as_view(),          name="login"),
    path("fan/register/",    FanRegisterView.as_view(),    name="fan_register"),
    path("fan/login/",       FanLoginView.as_view(),       name="fan_login"),
    path("oauth/google/",    GoogleOAuthView.as_view(),    name="oauth_google"),
    path("oauth/apple/",     AppleOAuthView.as_view(),     name="oauth_apple"),
    path("token/refresh/",   TokenRefreshView.as_view(),   name="token_refresh"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("reset-password/",  ResetPasswordView.as_view(),  name="reset_password"),

    # Protected
    path("me/",     MeView.as_view(),    name="me"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
