"""
Shared test base — imported by every test module in the project.

Provides:
- BaseAPITestCase  factory helpers (create_player, create_admin, create_team)
- JWT credential helpers (authenticate_as)
- Common assertions (assert_error_detail)
"""
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.applications.models import Application
from apps.teams.services import TeamService
from apps.users.models import PlayerProfile, User
from apps.users.services import UserService

TEST_PASSWORD = "Str0ng!Pass99"


class BaseAPITestCase(APITestCase):
    """
    Base class for all integration tests.

    Sets up a standard cast of users and provides helper methods
    so individual test classes need minimal boilerplate.
    """

    # ------------------------------------------------------------------
    # User factories
    # ------------------------------------------------------------------

    def create_player(
        self,
        email: str = "player@test.com",
        password: str = TEST_PASSWORD,
    ) -> User:
        """Create a player user with an attached PlayerProfile."""
        return UserService.create_user(email=email, password=password, role="player")

    def create_admin(
        self,
        email: str = "admin@test.com",
        password: str = TEST_PASSWORD,
    ) -> User:
        """Create an admin user (no PlayerProfile)."""
        return User.objects.create_user(
            email=email,
            password=password,
            role=User.Role.ADMIN,
        )

    # ------------------------------------------------------------------
    # Team factory
    # ------------------------------------------------------------------

    def create_team(
        self,
        captain: User,
        name: str = "Test FC",
        max_players: int = 11,
    ):
        """Create a team and assign its captain via TeamService."""
        return TeamService.create_team(
            captain=captain,
            name=name,
            max_players=max_players,
        )

    # ------------------------------------------------------------------
    # Application factory
    # ------------------------------------------------------------------

    def create_captain_application(
        self,
        applicant: User,
        team_name: str = "New Team FC",
    ) -> Application:
        from apps.applications.services import ApplicationService

        return ApplicationService.create_application(
            applicant=applicant,
            app_type=Application.Type.CAPTAIN,
            metadata={"team_name": team_name},
        )

    def create_free_agent_application(
        self,
        applicant: User,
        team,
    ) -> Application:
        from apps.applications.services import ApplicationService

        return ApplicationService.create_application(
            applicant=applicant,
            app_type=Application.Type.FREE_AGENT,
            team=team,
        )

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def get_access_token(self, user: User) -> str:
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def authenticate_as(self, user: User) -> None:
        """Set the client JWT credentials for *user*."""
        token = self.get_access_token(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def deauthenticate(self) -> None:
        """Clear any credentials from the test client."""
        self.client.credentials()

    # ------------------------------------------------------------------
    # Custom assertions
    # ------------------------------------------------------------------

    def assert_status(self, response, expected_status: int) -> None:
        self.assertEqual(
            response.status_code,
            expected_status,
            msg=f"Expected {expected_status}, got {response.status_code}. "
                f"Response: {getattr(response, 'data', response.content)}",
        )

    def assert_field_error(self, response, field: str) -> None:
        """Assert that the response contains a validation error for *field*."""
        detail = response.data.get("error", {}).get("detail", response.data)
        self.assertIn(
            field,
            detail,
            msg=f"Expected error on field '{field}'. Got: {detail}",
        )
