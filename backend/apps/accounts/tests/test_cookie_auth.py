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
        """
        Failed logins are throttled per (username, IP) combo (5/min).
        5 failed attempts from IP1 on UserA does NOT lock out UserA from IP2.
        Successful login resets ONLY combo_key, while pure IP counter keeps accumulating.
        """
        client = APIClient()
        cache.clear()

        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS):
            # 1. 5 consecutive failed attempts from IP1 (192.168.1.50) on authtestuser
            for _ in range(5):
                resp = client.post(
                    "/api/auth/login/",
                    {"username": "authtestuser", "password": "WrongPassword!"},
                    format="json",
                    HTTP_ORIGIN=TEST_ORIGIN,
                    REMOTE_ADDR="192.168.1.50",
                )
                assert resp.status_code == status.HTTP_401_UNAUTHORIZED

            # 6th attempt from IP1 on authtestuser is throttled (combo reached 5)
            throttled_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "WrongPassword!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
                REMOTE_ADDR="192.168.1.50",
            )
            assert throttled_resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS

            # 2. Legitimate user logging in from IP2 (10.0.0.99) is NOT locked out
            legit_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
                REMOTE_ADDR="10.0.0.99",
            )
            assert legit_resp.status_code == status.HTTP_200_OK

            # 3. Successful login resets ONLY combo_key, NEVER pure-IP counter
            # IP1 has 5 failed attempts in pure-IP counter (limit is 20)
            assert cache.get("failed_login_ip:192.168.1.50") == 5
            # Now let authtestuser log in successfully from IP1
            # First reset combo counter manually so it's not blocked by combo
            cache.delete("failed_login_combo:192.168.1.50:authtestuser")
            success_resp = client.post(
                "/api/auth/login/",
                {"username": "authtestuser", "password": "ValidPassword123!"},
                format="json",
                HTTP_ORIGIN=TEST_ORIGIN,
                REMOTE_ADDR="192.168.1.50",
            )
            assert success_resp.status_code == status.HTTP_200_OK
            # Combo key is deleted
            assert cache.get("failed_login_combo:192.168.1.50:authtestuser") is None
            # Pure IP counter is still intact (never reset on successful login)
            assert cache.get("failed_login_ip:192.168.1.50") == 5

    def test_login_throttling_trusted_ip_and_spoofed_header(self, auth_user):
        """Spoofed X-Forwarded-For cannot manipulate the client IP or throttle bucket."""
        client = APIClient()
        cache.clear()

        # Case A: NUM_PROXIES = 1 (production behind 1 proxy)
        # Client sends spoofed header: "1.1.1.1, 2.2.2.2"
        # The trusted client IP is 2.2.2.2 (ips[-1]), ignoring 1.1.1.1
        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS, NUM_PROXIES=1):
            for _ in range(5):
                resp = client.post(
                    "/api/auth/login/",
                    {"username": "authtestuser", "password": "WrongPassword!"},
                    format="json",
                    HTTP_ORIGIN=TEST_ORIGIN,
                    REMOTE_ADDR="127.0.0.1",
                    HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2",
                )
                assert resp.status_code == status.HTTP_401_UNAUTHORIZED

            # The combo counter should be under the trusted proxy IP 2.2.2.2, NOT 1.1.1.1
            assert cache.get("failed_login_combo:2.2.2.2:authtestuser") == 5
            assert cache.get("failed_login_combo:1.1.1.1:authtestuser") is None

        # Case B: NUM_PROXIES = 0 (direct connection / dev)
        # Client sends spoofed header: "1.1.1.1"
        # With NUM_PROXIES = 0, REMOTE_ADDR is used unconditionally
        cache.clear()
        with override_settings(ALLOWED_ORIGINS=TEST_ALLOWED_ORIGINS, NUM_PROXIES=0):
            for _ in range(5):
                resp = client.post(
                    "/api/auth/login/",
                    {"username": "authtestuser", "password": "WrongPassword!"},
                    format="json",
                    HTTP_ORIGIN=TEST_ORIGIN,
                    REMOTE_ADDR="192.168.1.77",
                    HTTP_X_FORWARDED_FOR="1.1.1.1",
                )
                assert resp.status_code == status.HTTP_401_UNAUTHORIZED

            assert cache.get("failed_login_combo:192.168.1.77:authtestuser") == 5
            assert cache.get("failed_login_combo:1.1.1.1:authtestuser") is None

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

    def test_cache_configuration(self):
        """Verify production settings specify RedisCache and test settings use LocMemCache."""
        from django.conf import settings
        from config import settings as prod_settings

        # In current test runtime, settings_test is active
        assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.locmem.LocMemCache"

        # In production settings module, RedisCache is defined
        assert prod_settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
        assert "redis://" in prod_settings.CACHES["default"]["LOCATION"]

