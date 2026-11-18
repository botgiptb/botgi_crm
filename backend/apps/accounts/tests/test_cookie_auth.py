import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import User

TEST_ORIGIN = "http://localhost:4200"
TEST_ALLOWED_ORIGINS = ["http://localhost:4200", "http://localhost:8000"]


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        username="authtestuser",
        email="authtest@example.com",
        password="ValidPassword123!",
        role=User.Role.STAFF,
        first_name="Auth",
        last_name="Tester",
    )
    return user


@pytest.mark.django_db
class TestCookieAuthentication:
    """Comprehensive test suite for cookie-based authentication, rotation, blacklist, and throttling."""

    def test_origin_verification_enforced(self, auth_user):
        """Endpoints reject missing or unauthorized Origin and Referer headers."""
        client = APIClient()

        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS):
            # 1. Missing both Origin and Referer -> 403 Forbidden
            resp_no_origin = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
            )
            assert resp_no_origin.status_code == status.HTTP_403_FORBIDDEN

            # 2. Malicious / unallowed Origin -> 403 Forbidden
            resp_evil = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN="https://evil-attacker.com",
            )
            assert resp_evil.status_code == status.HTTP_403_FORBIDDEN

            # 3. Allowed Origin -> Accepted
            resp_ok = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert resp_ok.status_code == status.HTTP_200_OK

            # 4. Fallback to Referer -> Accepted
            resp_referer = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_REFERER="http://localhost:4200/auth/login",
            )
            assert resp_referer.status_code == status.HTTP_200_OK

    def test_cookie_flags_and_secure_toggle(self, auth_user):
        """Verify httpOnly, samesite=Lax, path=/api/auth/, and configurable Secure flag."""
        client = APIClient()

        # Test with JWT_COOKIE_SECURE=False
        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS, JWT_COOKIE_SECURE=False):
            resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert resp.status_code == status.HTTP_200_OK
            assert "refresh_token" in resp.cookies
            cookie = resp.cookies["refresh_token"]
            assert cookie["httponly"] is True
            assert cookie["samesite"] == "Lax"
            assert cookie["path"] == "/api/auth/"
            assert not cookie["secure"]

        # Test with JWT_COOKIE_SECURE=True
        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS, JWT_COOKIE_SECURE=True):
            resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert resp.status_code == status.HTTP_200_OK
            cookie = resp.cookies["refresh_token"]
            assert cookie["secure"] is True

    def test_token_rotation_and_blacklisted_token_reuse_rejected(self, auth_user):
        """Refresh rotates token, sets new cookie, and rejects reuse of previous refresh token."""
        client = APIClient()

        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS):
            # 1. Initial Login
            login_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert login_resp.status_code == status.HTTP_200_OK
            initial_refresh = login_resp.cookies["refresh_token"].value
            initial_access = login_resp.data["access"]

            # 2. First Refresh using initial cookie
            client.cookies["refresh_token"] = initial_refresh
            refresh_resp = client.post(
                "/api/auth/refresh/",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert refresh_resp.status_code == status.HTTP_200_OK
            new_access = refresh_resp.data["access"]
            new_refresh = refresh_resp.cookies["refresh_token"].value

            assert new_access != initial_access
            assert new_refresh != initial_refresh

            # 3. Old refresh token is now blacklisted in database
            assert OutstandingToken.objects.filter(token=initial_refresh).exists()
            assert BlacklistedToken.objects.filter(token__token=initial_refresh).exists()

            # 4. Attempting to reuse the initial (now blacklisted) token is REJECTED with 401
            client.cookies["refresh_token"] = initial_refresh
            reuse_resp = client.post(
                "/api/auth/refresh/",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert reuse_resp.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Invalid or expired" in reuse_resp.data["detail"]

    def test_inactive_user_refresh_rejected(self, auth_user):
        """If user account is deactivated, refresh is rejected and token is blacklisted."""
        client = APIClient()

        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS):
            # Log in
            resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            refresh_token = resp.cookies["refresh_token"].value

            # Deactivate user
            auth_user.is_active = False
            auth_user.save(update_fields=["is_active"])

            # Attempt refresh
            client.cookies["refresh_token"] = refresh_token
            ref_resp = client.post(
                "/api/auth/refresh/",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert ref_resp.status_code == status.HTTP_401_UNAUTHORIZED
            assert "inactive" in ref_resp.data["detail"]
            assert BlacklistedToken.objects.filter(token__token=refresh_token).exists()

    def test_login_throttling_per_ip_and_username(self, auth_user):
        """Failed logins are throttled per IP and per username (5 failed attempts per min)."""
        client = APIClient()
        cache.clear()

        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS):
            # 5 consecutive failed attempts from IP 192.168.1.50
            for i in range(5):
                resp = client.post(
                    "/api/auth/login/",
                    {"username": "authtestuser", "password": "WrongPassword!"},
                    format="json",
                    HTTP_ORIGIN=TEST_ORIGIN,
                    REMOTE_ADDR="192.168.1.50",
                )
                assert resp.status_code == status.HTTP_401_UNAUTHORIZED

            # 6th attempt from same IP is throttled
            throttled_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "WrongPassword!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
                REMOTE_ADDR="192.168.1.50",
            )
            assert throttled_resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS

            # Another IP targeting the same username is ALSO throttled (per-username protection)
            attacker_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "WrongPassword!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
                REMOTE_ADDR="10.0.0.99",
            )
            assert attacker_resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS

            # Reset cache, successful login clears failure counts
            cache.clear()
            success_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
                REMOTE_ADDR="192.168.1.50",
            )
            assert success_resp.status_code == status.HTTP_200_OK

    def test_logout_blacklists_cookie_token_and_clears_cookie_idempotently(self, auth_user):
        """Logout blacklists refresh token, clears cookie, and succeeds even without access token."""
        client = APIClient()

        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS):
            # Login
            resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            refresh_val = resp.cookies["refresh_token"].value

            # Logout without Authorization header
            client.cookies["refresh_token"] = refresh_val
            logout_resp = client.post(
                "/api/auth/logout/",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert logout_resp.status_code == status.HTTP_200_OK
            assert logout_resp.data["message"] == "Logged out successfully."

            # Verify token is blacklisted
            assert BlacklistedToken.objects.filter(token__token=refresh_val).exists()

            # Verify cookie is cleared
            cleared_cookie = logout_resp.cookies["refresh_token"]
            assert cleared_cookie.value == ""

            # Calling logout again is idempotent
            second_logout = client.post(
                "/api/auth/logout/",
                HTTP_ORIGIN=TEST_ORIGIN,
            )
            assert second_logout.status_code == status.HTTP_200_OK
