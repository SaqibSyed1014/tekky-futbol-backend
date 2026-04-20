from django.urls import path

from .views import UserMeView

app_name = "users"

urlpatterns = [
    path("me/", UserMeView.as_view(), name="me"),
]
