import logging

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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
    PlayerProfileUpdateSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserUpdateSerializer,
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

    def _fetch_user(self, pk):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return (
            User.objects.select_related("profile__team", "waiver_signature")
            .get(pk=pk)
        )

    def get(self, request: Request) -> Response:
        user = self._fetch_user(request.user.pk)
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


# ---------------------------------------------------------------------------
# PATCH /users/me/  (add to MeView via separate mixin)
# ---------------------------------------------------------------------------


class UpdateUserView(APIView):
    """
    PATCH /users/me/ — update own name, phone, gender.

    Permission: authenticated users only (IsOwner enforced via lookup).
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = (
            User.objects.select_related("profile__team", "waiver_signature")
            .get(pk=request.user.pk)
        )
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        user.refresh_from_db()
        user = (
            User.objects.select_related("profile__team", "waiver_signature")
            .get(pk=user.pk)
        )
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# PATCH /users/profile/me/
# ---------------------------------------------------------------------------


class UpdatePlayerProfileView(APIView):
    """
    PATCH /users/profile/me/ — update own PlayerProfile fields
    (position, bio, date_of_birth, preferred_division, instagram).

    Only available to users with a PlayerProfile (role=player / is_captain).

    Permission: authenticated users only.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        profile = getattr(request.user, "profile", None)
        if profile is None:
            return Response(
                {"detail": "No player profile associated with this account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PlayerProfileUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        user = (
            User.objects.select_related("profile__team", "waiver_signature")
            .get(pk=request.user.pk)
        )
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# DELETE /users/me/
# ---------------------------------------------------------------------------


class DeleteAccountView(APIView):
    """
    DELETE /users/me/ — permanently delete own account and all related data.

    Cascades through PROTECT / RESTRICT relations in the correct order so
    Django's FK guards never block the final user.delete().

    Permission: authenticated users only.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request: Request) -> Response:
        from apps.applications.models import Application, FreeAgent
        from apps.teams.models import Team, TeamInvite, TeamMembership
        from apps.waivers.models import WaiverSignature

        user = request.user
        uid = user.id

        # 1 — WaiverSignature (PROTECT)
        WaiverSignature.objects.filter(user_id=uid).delete()
        # 2 — TeamInvites sent by this user (PROTECT on invited_by)
        TeamInvite.objects.filter(invited_by_id=uid).delete()
        # 3 — TeamMembership (PROTECT)
        TeamMembership.objects.filter(user_id=uid).delete()
        # 4 — Applications (RESTRICT on applicant)
        Application.objects.filter(applicant_id=uid).delete()
        # 5 — FreeAgent (CASCADE, but explicit for clarity)
        FreeAgent.objects.filter(user_id=uid).delete()
        # 6 — Team where this user is captain (RESTRICT via OneToOneField)
        Team.objects.filter(captain_id=uid).delete()
        # 7 — User (PlayerProfile cascades automatically)
        logger.info("User %s requested account deletion", uid)
        user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# POST /auth/forgot-password/
# ---------------------------------------------------------------------------


class ForgotPasswordView(APIView):
    """
    POST /auth/forgot-password/

    Accepts { "email": "..." } and sends a password-reset email if the
    address matches an active account.

    Always returns 200 with the same message regardless of whether the
    email was found — prevents email enumeration.

    Permission: public.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        email = request.data.get("email", "").strip().lower()
        if not email:
            return Response(
                {"email": "Email address is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _SAFE = {"detail": "If that email is registered you will receive a reset link shortly."}

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response(_SAFE, status=status.HTTP_200_OK)

        uid   = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_url = (
            f"{getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:3000')}"
            f"/reset-password?uid={uid}&token={token}"
        )

        send_mail(
            subject="Reset your TekkyFutbol password",
            message=(
                f"Hi {user.name or user.email},\n\n"
                f"Click the link below to reset your password. "
                f"This link expires in 24 hours.\n\n"
                f"{reset_url}\n\n"
                f"If you did not request a password reset, ignore this email.\n\n"
                f"— TekkyFutbol"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@tekkyfutbol.com"),
            recipient_list=[user.email],
            fail_silently=True,
        )

        logger.info("Password reset email dispatched for user %s", user.id)
        return Response(_SAFE, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# POST /auth/reset-password/
# ---------------------------------------------------------------------------


class ResetPasswordView(APIView):
    """
    POST /auth/reset-password/

    Accepts { "uid", "token", "new_password", "confirm_password" } and
    resets the user's password if the token is valid and unexpired.

    Uses Django's built-in PasswordResetTokenGenerator (HMAC-based,
    24-hour expiry by default via PASSWORD_RESET_TIMEOUT setting).

    Permission: public.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        uid              = request.data.get("uid", "")
        token            = request.data.get("token", "")
        new_password     = request.data.get("new_password", "")
        confirm_password = request.data.get("confirm_password", "")

        # Decode uid → user
        try:
            user_pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "This reset link is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate the HMAC token
        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "This reset link has expired or has already been used."},
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
        logger.info("Password reset completed for user %s", user.id)

        return Response(
            {"detail": "Your password has been reset. You can now log in."},
            status=status.HTTP_200_OK,
        )
