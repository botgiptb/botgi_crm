from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """Allows access only to admin users."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_admin_role", False)
        )


class IsManagerRole(BasePermission):
    """Allows access only to manager users."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_manager_role", False)
        )


class IsManagerOrAdmin(BasePermission):
    """Allows access to managers or admins."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                getattr(request.user, "is_admin_role", False)
                or getattr(request.user, "is_manager_role", False)
            )
        )


class IsStaffRole(BasePermission):
    """Allows access only to regular staff members."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_staff_role", False)
        )
