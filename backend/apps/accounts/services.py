from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User


class UserService:
    """Service handling user account lifecycle and role assignment."""

    @staticmethod
    @transaction.atomic
    def create_user(
        *,
        username: str,
        email: str,
        password: str,
        role: str = User.Role.STAFF,
        phone: str = "",
        receives_meta_leads: bool = False,
        first_name: str = "",
        last_name: str = "",
    ) -> User:
        """Create a user with validated role and fields."""
        if role not in User.Role.values:
            raise ValidationError(
                {"role": f"Invalid role: {role}. Must be one of {User.Role.values}."}
            )

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError({"email": "A user with this email already exists."})

        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError({"username": "A user with this username already exists."})

        return User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            phone=phone,
            receives_meta_leads=receives_meta_leads,
            first_name=first_name,
            last_name=last_name,
        )

    @staticmethod
    @transaction.atomic
    def update_user(user: User, **fields: Any) -> User:
        """Update user profile fields with validation."""
        role = fields.get("role")
        if role and role not in User.Role.values:
            raise ValidationError(
                {"role": f"Invalid role: {role}. Must be one of {User.Role.values}."}
            )

        email = fields.get("email")
        if email and User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
            raise ValidationError({"email": "A user with this email already exists."})

        password = fields.pop("password", None)
        if password:
            user.set_password(password)

        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)

        user.full_clean()
        user.save()
        return user

    @staticmethod
    def get_assignable_users():
        """Return active users who can be assigned leads (staff and managers)."""
        return User.objects.filter(
            is_active=True,
            role__in=[User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN],
        ).order_by("first_name", "username")
