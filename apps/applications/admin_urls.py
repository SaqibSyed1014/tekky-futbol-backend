from django.urls import path

from .views import AdminApplicationListView, AdminApplicationUpdateView

# Mounted at /api/v1/admin/ in config/urls.py
# Final URLs:
#   GET  /api/v1/admin/applications/
#   PATCH /api/v1/admin/applications/{id}/

app_name = "admin_applications"

urlpatterns = [
    path("applications/", AdminApplicationListView.as_view(), name="list"),
    path("applications/<uuid:pk>/", AdminApplicationUpdateView.as_view(), name="update"),
]
