from rest_framework.permissions import BasePermission

from .models import WaiverSignature


class HasSignedWaiver(BasePermission):
    """
    Allows access only to authenticated users who have signed the waiver.

    Returns a structured error so the frontend can detect 'waiver_required'
    and redirect the user to /user/waiver instead of showing a generic 403.
    """
    message = {"error": "waiver_required", "detail": "You must sign the waiver before accessing this feature."}

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return WaiverSignature.objects.filter(user=request.user).exists()
