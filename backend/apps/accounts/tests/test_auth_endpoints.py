import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService


@pytest.mark.django_db
class TestAuthEndpoints:
    def setup_method(self):
        self.client = APIClient()
        self.user = UserService.create_user(
            username="testuser",
            email="testuser@example.com",
            password="StrongPassword123",
            role=User.Role.STAFF,
            phone="+919123456789",
            first_name="Test",
            last_name="User",
        )

    def test_token_obtain_success(self):
        response = self.client.post(
            "/api/auth/token/",
            {"username": "testuser", "password": "StrongPassword123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
        assert "user" in response.data
        assert response.data["user"]["username"] == "testuser"
        assert response.data["user"]["role"] == User.Role.STAFF
        assert response.data["user"]["email"] == "testuser@example.com"

    def test_token_obtain_invalid_credentials(self):
        response = self.client.post(
            "/api/auth/token/",
            {"username": "testuser", "password": "WrongPassword"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_refresh(self):
        login_response = self.client.post(
            "/api/auth/token/",
            {"username": "testuser", "password": "StrongPassword123"},
            format="json",
        )
        refresh_token = login_response.data["refresh"]

        refresh_response = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        assert refresh_response.status_code == status.HTTP_200_OK
        assert "access" in refresh_response.data

    def test_get_current_user_profile_unauthenticated(self):
        response = self.client.get("/api/auth/me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_current_user_profile_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["username"] == "testuser"
        assert response.data["email"] == "testuser@example.com"
        assert response.data["role"] == User.Role.STAFF

    def test_update_current_user_profile(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/auth/me/",
            {"first_name": "NewFirst", "phone": "+919876543210"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["first_name"] == "NewFirst"
        assert response.data["phone"] == "+919876543210"

        self.user.refresh_from_db()
        assert self.user.first_name == "NewFirst"
        assert self.user.phone == "+919876543210"
