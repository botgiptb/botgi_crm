from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    CurrentUserProfileView,
    CustomTokenObtainPairView,
    UserViewSet,
)

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    path("auth/token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/me/", CurrentUserProfileView.as_view(), name="current_user_profile"),
    path("", include(router.urls)),
]
