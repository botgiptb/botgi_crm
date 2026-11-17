import pytest

from apps.accounts.models import User


@pytest.mark.django_db
class TestUserModel:
    def test_create_staff_user(self):
        user = User.objects.create_user(
            username="staff1",
            email="staff1@example.com",
            password="testpassword123",
            role=User.Role.STAFF,
        )
        assert user.id is not None
        assert user.role == User.Role.STAFF
        assert user.is_staff_role is True
        assert user.is_admin_role is False
        assert user.is_manager_role is False
        assert user.can_view_all_leads is False

    def test_create_manager_user(self):
        user = User.objects.create_user(
            username="manager1",
            email="manager1@example.com",
            password="testpassword123",
            role=User.Role.MANAGER,
        )
        assert user.role == User.Role.MANAGER
        assert user.is_manager_role is True
        assert user.can_view_all_leads is True

    def test_create_admin_user(self):
        user = User.objects.create_user(
            username="admin1",
            email="admin1@example.com",
            password="testpassword123",
            role=User.Role.ADMIN,
        )
        assert user.role == User.Role.ADMIN
        assert user.is_admin_role is True
        assert user.is_staff is True
        assert user.can_view_all_leads is True

    def test_create_superuser(self):
        user = User.objects.create_superuser(
            username="superadmin",
            email="superadmin@example.com",
            password="testpassword123",
        )
        assert user.is_superuser is True
        assert user.is_staff is True
        assert user.role == User.Role.ADMIN
        assert user.is_admin_role is True
        assert user.can_view_all_leads is True

    def test_email_must_be_set(self):
        with pytest.raises(ValueError, match="The Email field must be set"):
            User.objects.create_user(
                username="noemail",
                email="",
                password="testpassword123",
            )

    def test_username_must_be_set(self):
        with pytest.raises(ValueError, match="The Username field must be set"):
            User.objects.create_user(
                username="",
                email="nouser@example.com",
                password="testpassword123",
            )
