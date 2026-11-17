from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminRole, IsManagerOrAdmin
from apps.accounts.serializers import (
    CustomTokenObtainPairSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from apps.accounts.services import UserService


class CustomTokenObtainPairView(TokenObtainPairView):
    """Obtain JWT tokens with user profile information."""

    serializer_class = CustomTokenObtainPairSerializer


class CurrentUserProfileView(APIView):
    """View and update current logged-in user profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        allowed_fields = {"first_name", "last_name", "phone"}
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        updated_user = UserService.update_user(request.user, **update_data)
        return Response(UserSerializer(updated_user).data)


class UserViewSet(viewsets.ModelViewSet):
    """Manage team members and roles."""

    queryset = User.objects.all().order_by("-id")

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action in ["update", "partial_update"]:
            return UserUpdateSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action in ["create", "destroy"]:
            permission_classes = [IsAdminRole]
        elif self.action in ["list", "retrieve", "update", "partial_update"]:
            permission_classes = [IsManagerOrAdmin]
        elif self.action == "assignable":
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def assignable(self, request):
        """List active users available for lead assignment."""
        users = UserService.get_assignable_users()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)
