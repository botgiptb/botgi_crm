from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.models import User
from apps.accounts.services import UserService


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom SimpleJWT serializer providing user details and role claims."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        token["email"] = user.email
        token["role"] = user.role
        token["is_admin"] = user.is_admin_role
        token["is_manager"] = user.is_manager_role
        token["is_staff_role"] = user.is_staff_role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        data["user"] = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "phone": user.phone,
        }
        return data


class UserSerializer(serializers.ModelSerializer):
    """Serializer for representation of User details."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "phone",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for user creation, calling UserService."""

    password = serializers.CharField(write_only=True, required=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "role",
            "phone",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        return UserService.create_user(**validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for user updates, calling UserService."""

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "role",
            "phone",
            "is_active",
        ]

    def update(self, instance, validated_data):
        return UserService.update_user(instance, **validated_data)
