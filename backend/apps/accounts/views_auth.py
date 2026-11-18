import logging
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.common.utils import get_client_ip

logger = logging.getLogger(__name__)

COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/auth/"


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.CharField(help_text="Username or email")
    password = serializers.CharField(write_only=True)


class AuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Short-lived in-memory JWT access token")
    user = UserSerializer()


class LogoutResponseSerializer(serializers.Serializer):
    message = serializers.CharField()


def verify_origin(request) -> bool:
    """
    Verify that request Origin (fallback Referer, reject if both missing)
    matches the configured ALLOWED_ORIGINS allowlist exactly (scheme + host + optional port).
    Prevents CSRF on cookie-based authentication endpoints.
    """
    origin = request.headers.get("Origin")
    if not origin:
        referer = request.headers.get("Referer")
        if referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                origin = f"{parsed.scheme}://{parsed.netloc}"

    if not origin:
        return False

    origin = origin.rstrip("/")
    allowed = {o.rstrip("/") for o in getattr(settings, "ALLOWED_ORIGINS", []) if o.strip()}
    return origin in allowed


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attach rotated refresh token in a secure, httpOnly cookie restricted to auth endpoints."""
    secure = getattr(settings, "JWT_COOKIE_SECURE", True)
    lifetime = settings.SIMPLE_JWT.get("REFRESH_TOKEN_LIFETIME")
    max_age = int(lifetime.total_seconds()) if lifetime else 7 * 86400

    response.set_cookie(
        key=COOKIE_NAME,
        value=refresh_token,
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path=COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie upon logout or token invalidation."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
    )


def is_login_throttled(client_ip: str, username: str) -> bool:
    """
    Check if failed login threshold has been reached:
    - (username, IP) combination: 5 failed attempts per min
    - Pure IP: 20 failed attempts per min (prevents credential spraying)
    - Username backstop: 30 failed attempts per hour (prevents distributed brute-force)
    """
    clean_user = username.lower().strip()
    combo_key = f"failed_login_combo:{client_ip}:{clean_user}"
    user_key = f"failed_login_user:{clean_user}"
    ip_key = f"failed_login_ip:{client_ip}"

    combo_fails = cache.get(combo_key) or 0
    user_fails = cache.get(user_key) or 0
    ip_fails = cache.get(ip_key) or 0

    return combo_fails >= 5 or user_fails >= 30 or ip_fails >= 20


def record_failed_login(client_ip: str, username: str) -> None:
    """Increment failed login attempt counts for (ip, user) combo, user backstop, and IP."""
    clean_user = username.lower().strip()
    combo_key = f"failed_login_combo:{client_ip}:{clean_user}"
    user_key = f"failed_login_user:{clean_user}"
    ip_key = f"failed_login_ip:{client_ip}"

    for key, timeout in [(combo_key, 60), (user_key, 3600), (ip_key, 60)]:
        val = cache.get(key)
        if val is None:
            cache.set(key, 1, timeout=timeout)
        else:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, val + 1, timeout=timeout)


def clear_failed_logins(client_ip: str, username: str) -> None:
    """
    Reset ONLY the (username, IP) combo counter on successful login.
    Never resets pure-IP counter to prevent attackers resetting IP quota.
    """
    clean_user = username.lower().strip()
    combo_key = f"failed_login_combo:{client_ip}:{clean_user}"
    cache.delete(combo_key)


class CookieLoginView(APIView):
    """
    Authenticate user credentials, return in-memory access token,
    and set the rotated refresh token in an httpOnly cookie.
    Throttles failed login attempts per (username, IP) combo, IP, and username.
    Enforces origin verification against ALLOWED_ORIGINS.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=LoginRequestSerializer,
        responses={200: AuthResponseSerializer},
        summary="Login and obtain in-memory access token with httpOnly refresh cookie",
    )
    def post(self, request):
        if not verify_origin(request):
            return Response(
                {"detail": "Origin or Referer not allowed or missing."},
                status=status.HTTP_403_FORBIDDEN,
            )

        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")
        client_ip = get_client_ip(request)

        if not username or not password:
            return Response(
                {"detail": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if is_login_throttled(client_ip, username):
            return Response(
                {"detail": "Too many failed login attempts. Please try again in 1 minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(request, username=username, password=password)
        if not user:
            record_failed_login(client_ip, username)
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"detail": "Account is inactive. Please contact an administrator."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        clear_failed_logins(client_ip, username)

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        response = Response(
            {
                "access": access_token,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
        set_refresh_cookie(response, str(refresh))
        return response


class CookieTokenRefreshView(APIView):
    """
    Silent token refresh: reads refresh token from httpOnly cookie,
    verifies user is active, rotates refresh token, and returns a new access token.
    Enforces origin verification against ALLOWED_ORIGINS.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        responses={200: AuthResponseSerializer},
        summary="Rotate refresh token cookie and obtain fresh access token",
    )
    def post(self, request):
        if not verify_origin(request):
            return Response(
                {"detail": "Origin or Referer not allowed or missing."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cookie_token = request.COOKIES.get(COOKIE_NAME)
        if not cookie_token:
            return Response(
                {"detail": "Refresh token cookie missing."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            token = RefreshToken(cookie_token)
            user_id = token.payload.get("user_id")
        except TokenError as exc:
            response = Response(
                {"detail": f"Invalid or expired refresh token: {str(exc)}"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            clear_refresh_cookie(response)
            return response

        user = User.objects.filter(pk=user_id).first()
        if not user or not user.is_active:
            try:
                token.blacklist()
            except Exception:
                pass
            response = Response(
                {"detail": "User account is inactive or not found."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            clear_refresh_cookie(response)
            return response

        # Rotate token: blacklist old token, mint new one
        try:
            token.blacklist()
        except Exception:
            pass

        new_refresh = RefreshToken.for_user(user)
        response = Response(
            {
                "access": str(new_refresh.access_token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
        set_refresh_cookie(response, str(new_refresh))
        return response


class CookieLogoutView(APIView):
    """
    Log out: blacklists the refresh token in database (even if access token is expired),
    clears httpOnly cookie, and returns 200 OK. Idempotent.
    Enforces origin verification against ALLOWED_ORIGINS.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        responses={200: LogoutResponseSerializer},
        summary="Logout by blacklisting refresh token and clearing cookie",
    )
    def post(self, request):
        if not verify_origin(request):
            return Response(
                {"detail": "Origin or Referer not allowed or missing."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cookie_token = request.COOKIES.get(COOKIE_NAME)
        if cookie_token:
            try:
                token = RefreshToken(cookie_token)
                token.blacklist()
            except Exception:
                # Idempotent: already blacklisted or expired token still results in clean cookie clearing
                pass

        response = Response(
            {"message": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )
        clear_refresh_cookie(response)
        return response
