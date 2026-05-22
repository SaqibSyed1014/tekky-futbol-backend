import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.core.permissions import IsOwner

from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserDetailSerializer,
)
from .services import UserService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


class RegisterView(APIView):
    """
    Register a new user account.

    - Validates input via RegisterSerializer (email uniqueness, password
      strength, password match, role guard).
    - Delegates creation to UserService.create_user (creates User +
      PlayerProfile in one transaction for player role).
    - Returns JWT access + refresh tokens and the user payload in a single
      response so the client can authenticate immediately after registration.

    Permission: public — no authentication required.
    """

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer  # exposed for schema generation

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = UserService.create_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            role=serializer.validated_data.get("role", "player"),
        )

        refresh = RefreshToken.for_user(user)

        logger.info("New user registered: %s (role=%s)", user.id, user.role)

        access_token = str(refresh.access_token)
        return Response(
            {
                "token": access_token,   # frontend alias
                "access": access_token,
                "refresh": str(refresh),
                "user": UserDetailSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


class LogoutView(APIView):
    """
    Invalidate the caller's refresh token.

    The client passes { "refresh": "<token>" } in the request body.
    The token is blacklisted via simplejwt's built-in mechanism so it can
    never be used to mint a new access token.

    If no refresh token is supplied, or the token is already invalid, the
    response is still 200 — the client always clears localStorage regardless.

    Permission: authenticated users only (access token required in header).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except TokenError:
                pass  # already expired or blacklisted — no action needed

        logger.info("User %s logged out", request.user.id)
        return Response(status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


class LoginView(TokenObtainPairView):
    """
    Authenticate with email + password and receive JWT tokens.

    Extends simplejwt's TokenObtainPairView with CustomTokenObtainPairSerializer
    which embeds (email, role, is_captain) as custom JWT claims and appends
    the full user object to the HTTP response body.

    Response shape:
        { "access": "<jwt>", "refresh": "<jwt>", "user": { ... } }

    Permission: public — no authentication required.
    """

    serializer_class = CustomTokenObtainPairSerializer


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


class MeView(APIView):
    """
    Return the authenticated user's identity and profile.

    Permission:
        IsAuthenticated — request must carry a valid JWT.
        IsOwner         — object-level guard ensures the fetched User is the
                          caller (request.user == obj). Enforced via
                          check_object_permissions so no inline role check
                          is needed in the handler.

    Uses select_related("profile__team", "waiver_signature") to resolve
    the full response in a single DB query.
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request: Request) -> Response:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = (
            User.objects.select_related("profile__team", "waiver_signature")
            .get(pk=request.user.pk)
        )
        self.check_object_permissions(request, user)
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# GET /users/me
# ---------------------------------------------------------------------------


class UserMeView(APIView):
    """
    Return the authenticated user's full profile (canonical resource URL).

    Identical response shape to GET /auth/me — exposed under /users/ so
    clients can treat it as the stable user-profile endpoint independently
    of the auth flow.

    Permission:
        IsAuthenticated — request must carry a valid JWT.
        IsOwner         — object-level guard, enforced via
                          check_object_permissions.
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request: Request) -> Response:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = (
            User.objects.select_related("profile__team", "waiver_signature")
            .get(pk=request.user.pk)
        )
        self.check_object_permissions(request, user)
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# POST /users/change-password  (players only — admins have no UI for this)
# ---------------------------------------------------------------------------


class ChangePasswordView(APIView):
    """
    Change the authenticated user's password.

    Request body:
        { "old_password": "...", "new_password": "...", "confirm_password": "..." }

    Validates:
    - old_password matches the current password.
    - new_password passes Django's configured validators.
    - new_password == confirm_password.

    Permission: authenticated users only.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        user = request.user
        old_password     = request.data.get("old_password", "")
        new_password     = request.data.get("new_password", "")
        confirm_password = request.data.get("confirm_password", "")

        if not user.check_password(old_password):
            return Response(
                {"old_password": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"confirm_password": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            return Response(
                {"new_password": list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        logger.info("User %s changed their password", user.id)
        return Response(
            {"detail": "Password updated successfully."},
            status=status.HTTP_200_OK,
        )
