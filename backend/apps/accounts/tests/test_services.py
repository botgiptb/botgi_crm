import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.services import UserService


@pytest.mark.django_db
class TestUserService:
    def test_create_user_success(self):
        user = UserService.create_user(
            username="john_doe",
            email="john@example.com",
            password="securepassword123",
            role=User.Role.STAFF,
            phone="+919876543210",
            first_name="John",
            last_name="Doe",
        )
        assert user.id is not None
        assert user.username == "john_doe"
        assert user.email == "john@example.com"
        assert user.role == User.Role.STAFF
        assert user.phone == "+919876543210"
        assert user.check_password("securepassword123") is True

    def test_create_user_invalid_role(self):
        with pytest.raises(ValidationError) as exc:
            UserService.create_user(
                username="invalid_role_user",
                email="invalid@example.com",
                password="securepassword123",
                role="ceo",
            )
        assert "role" in exc.value.message_dict

    def test_create_user_duplicate_email(self):
        UserService.create_user(
            username="user1",
            email="duplicate@example.com",
            password="securepassword123",
        )
        with pytest.raises(ValidationError) as exc:
            UserService.create_user(
                username="user2",
                email="duplicate@example.com",
                password="securepassword123",
            )
        assert "email" in exc.value.message_dict

    def test_create_user_duplicate_username(self):
        UserService.create_user(
            username="same_user",
            email="user1@example.com",
            password="securepassword123",
        )
        with pytest.raises(ValidationError) as exc:
            UserService.create_user(
                username="same_user",
                email="user2@example.com",
                password="securepassword123",
            )
        assert "username" in exc.value.message_dict

    def test_update_user(self):
        user = UserService.create_user(
            username="update_me",
            email="update@example.com",
            password="securepassword123",
        )
        updated = UserService.update_user(
            user,
            first_name="UpdatedFirst",
            phone="+919999988888",
        )
        assert updated.first_name == "UpdatedFirst"
        assert updated.phone == "+919999988888"

    def test_get_assignable_users(self):
        UserService.create_user(
            username="active_staff",
            email="staff@example.com",
            password="securepassword123",
            role=User.Role.STAFF,
        )
        inactive = UserService.create_user(
            username="inactive_staff",
            email="inactive@example.com",
            password="securepassword123",
            role=User.Role.STAFF,
        )
        inactive.is_active = False
        inactive.save()

        assignable = UserService.get_assignable_users()
        usernames = [u.username for u in assignable]
        assert "active_staff" in usernames
        assert "inactive_staff" not in usernames
