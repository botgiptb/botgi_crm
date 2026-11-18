from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    CurrentUserProfileView,
    CustomTokenObtainPairView,
    UserViewSet,
)
from apps.accounts.views_auth import (
    CookieLoginView,
    CookieLogoutView,
    CookieTokenRefreshView,
)

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    # Cookie-based auth endpoints for same-origin frontend
    path("auth/login/", CookieLoginView.as_view(), name="auth_cookie_login"),
    path("auth/refresh/", CookieTokenRefreshView.as_view(), name="auth_cookie_refresh"),
    path("auth/logout/", CookieLogoutView.as_view(), name="auth_cookie_logout"),
    path("auth/me/", CurrentUserProfileView.as_view(), name="current_user_profile"),
    # Legacy / Direct JWT endpoints
    path("auth/token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("", include(router.urls)),
]
