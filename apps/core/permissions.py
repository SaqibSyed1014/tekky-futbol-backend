from rest_framework.permissions import BasePermission, IsAuthenticated  # noqa: F401 — re-exported for convenience



class IsAdmin(BasePermission):
    """
    Grants access only to authenticated users with role='admin'.

    Checks authentication internally so that unauthenticated requests receive
    401 (not 403), while authenticated non-admin requests receive 403.

    Usage:
        permission_classes = [IsAdmin]
    """

    message = "You must have admin role to perform this action."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )


class IsPlayer(BasePermission):
    """
    Grants access only to authenticated users with role='player'.

    Checks authentication internally — same 401/403 split as IsAdmin.

    Usage:
        permission_classes = [IsPlayer]
    """

    message = "You must have player role to perform this action."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "player"
        )


class IsOwner(BasePermission):
    """
    Object-level permission that restricts access to the owner of a resource.

    Must be used alongside a view-level authentication/role check.
    Only called automatically by DRF when the view calls get_object() or
    check_object_permissions(request, obj) explicitly.

    Ownership is resolved by inspecting the object in order:
        1. obj  == request.user          — the object IS the user (User model)
        2. obj.user == request.user      — object has a .user FK
        3. obj.applicant == request.user — object has an .applicant FK

    Usage (detail views):
        permission_classes = [IsAuthenticated, IsOwner]

        def get(self, request, pk):
            obj = get_object_or_404(Model, pk=pk)
            self.check_object_permissions(request, obj)
            ...
    """

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj) -> bool:
        # Case 1: the object itself is the user (e.g. User profile endpoints)
        if obj == request.user:
            return True

        # Case 2: the object belongs to a user via .user FK (e.g. PlayerProfile, FreeAgent)
        owner = getattr(obj, "user", None)
        if owner is not None:
            return owner == request.user

        # Case 3: the object belongs to a user via .applicant FK (e.g. Application)
        applicant = getattr(obj, "applicant", None)
        if applicant is not None:
            return applicant == request.user

        return False


class IsCaptain(BasePermission):
    """
    Grants access only to authenticated players who are captains of a team.

    Checks authentication internally — same 401/403 split as IsAdmin/IsPlayer.

    Usage:
        permission_classes = [IsCaptain]
    """

    message = "You must be a team captain to perform this action."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "player"
            and request.user.is_captain
        )
