from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Custom manager for User model supporting roles."""

    def create_user(self, username, email, password=None, role="staff", **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        if not username:
            raise ValueError("The Username field must be set")

        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        if role not in User.Role.values:
            role = User.Role.STAFF
        extra_fields["role"] = role

        # Sync Django admin access flags
        if role == User.Role.ADMIN:
            extra_fields.setdefault("is_staff", True)

        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        STAFF = "staff", "Staff"

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
        db_index=True,
    )
    phone = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ["-id"]
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.username} ({self.role})"

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_manager_role(self) -> bool:
        return self.role == self.Role.MANAGER

    @property
    def is_staff_role(self) -> bool:
        return self.role == self.Role.STAFF

    @property
    def can_view_all_leads(self) -> bool:
        return self.is_admin_role or self.is_manager_role
