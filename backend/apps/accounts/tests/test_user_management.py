import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService


@pytest.mark.django_db
class TestUserManagementAndPermissions:
    def setup_method(self):
        self.client = APIClient()
        self.admin = UserService.create_user(
            username="admin_user",
            email="admin@example.com",
            password="AdminPassword123",
            role=User.Role.ADMIN,
        )
        self.manager = UserService.create_user(
            username="manager_user",
            email="manager@example.com",
            password="ManagerPassword123",
            role=User.Role.MANAGER,
        )
        self.staff = UserService.create_user(
            username="staff_user",
            email="staff@example.com",
            password="StaffPassword123",
            role=User.Role.STAFF,
        )

    def test_staff_cannot_list_users(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/users/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_manager_can_list_users(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get("/api/users/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 3

    def test_manager_cannot_create_user(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(
            "/api/users/",
            {
                "username": "new_staff",
                "email": "new_staff@example.com",
                "password": "ValidPassword123",
                "role": User.Role.STAFF,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_create_user(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/users/",
            {
                "username": "new_staff_by_admin",
                "email": "created_by_admin@example.com",
                "password": "ValidPassword123",
                "role": User.Role.STAFF,
                "first_name": "Created",
                "last_name": "Staff",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["username"] == "new_staff_by_admin"
        assert User.objects.filter(username="new_staff_by_admin").exists()

    def test_admin_can_update_user(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            f"/api/users/{self.staff.id}/",
            {"role": User.Role.MANAGER},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        self.staff.refresh_from_db()
        assert self.staff.role == User.Role.MANAGER

    def test_any_authenticated_user_can_access_assignable_list(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/users/assignable/")
        assert response.status_code == status.HTTP_200_OK
        usernames = [u["username"] for u in response.data]
        assert "staff_user" in usernames
        assert "manager_user" in usernames
        assert "admin_user" in usernames
