from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import Activity, FollowUp, Notification
from apps.activities.serializers import (
    ActivitySerializer,
    CompleteFollowUpSerializer,
    FollowUpSerializer,
    NotificationSerializer,
)
from apps.activities.services import FollowUpService, NotificationService
from apps.leads.permissions import IsAssignedStaffOrManagerOrAdmin


class ActivityViewSet(viewsets.ModelViewSet):
    """
    Activity interaction viewset scoped through lead assignee.
    Staff see only activities for leads assigned to them.
    """

    serializer_class = ActivitySerializer
    permission_classes = [IsAuthenticated, IsAssignedStaffOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        base_qs = Activity.objects.select_related("lead", "user").order_by("-occurred_at")
        if getattr(user, "can_view_all_leads", False):
            return base_qs
        return base_qs.filter(lead__assigned_to=user)


class FollowUpViewSet(viewsets.ModelViewSet):
    """
    Follow-up reminders viewset scoped through lead assignee.
    """

    serializer_class = FollowUpSerializer
    permission_classes = [IsAuthenticated, IsAssignedStaffOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        base_qs = FollowUp.objects.select_related("lead", "assigned_to", "completed_by").order_by(
            "scheduled_at"
        )
        if getattr(user, "can_view_all_leads", False):
            return base_qs
        return base_qs.filter(lead__assigned_to=user)

    @action(detail=False, methods=["get"])
    def overdue(self, request):
        """List overdue pending follow-ups for current user/system."""
        qs = self.get_queryset().overdue()
        return Response(FollowUpSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark follow-up as completed."""
        follow_up = self.get_object()
        serializer = CompleteFollowUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            completed = FollowUpService.complete_follow_up(
                follow_up_id=follow_up.id,
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
            return Response(FollowUpSerializer(completed).data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel follow-up reminder."""
        follow_up = self.get_object()
        try:
            cancelled = FollowUpService.cancel_follow_up(
                follow_up_id=follow_up.id,
                user=request.user,
            )
            return Response(FollowUpSerializer(cancelled).data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    User in-app notifications.
    Strictly scoped to the authenticated user. Requests for other users' notifications return 404.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Notification.objects.filter(user=self.request.user)
            .select_related("lead", "follow_up")
            .order_by("-created_at")
        )

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        """Return the count of unread notifications for badge."""
        count = self.get_queryset().filter(read_at__isnull=True).count()
        return Response({"unread_count": count})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark single notification as read (returns 404 if not owned by request.user)."""
        notif = self.get_object()
        updated = NotificationService.mark_read(notif.id, request.user)
        return Response(NotificationSerializer(updated).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Mark all unread notifications as read for current user."""
        count = NotificationService.mark_all_read(request.user)
        return Response({"marked_read": count})
