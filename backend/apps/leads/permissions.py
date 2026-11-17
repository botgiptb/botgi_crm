from rest_framework.permissions import BasePermission


class IsAssignedStaffOrManagerOrAdmin(BasePermission):
    """
    Staff can only access/edit their assigned leads.
    Managers and Admins can access and edit all leads.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if getattr(request.user, "can_view_all_leads", False):
            return True

        # For Lead objects
        if hasattr(obj, "assigned_to"):
            return obj.assigned_to == request.user

        # For Customer objects: accessible if customer has any lead assigned to or created by staff
        if hasattr(obj, "leads"):
            return (
                obj.leads.filter(assigned_to=request.user).exists()
                or obj.leads.filter(created_by=request.user).exists()
            )

        # For nested objects (Activity, FollowUp, StageHistory, LeadAssignment)
        if hasattr(obj, "lead"):
            return obj.lead.assigned_to == request.user

        return False


class IsManagerOrAdminForCustomerPhone(BasePermission):
    """Allows modifying customer phone or deactivating customer only to Managers/Admins."""

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in ["PUT", "PATCH"]:
            restricted_fields = {"phone", "is_active"}
            if restricted_fields.intersection(set(request.data.keys())):
                return getattr(request.user, "can_view_all_leads", False)

        return True
