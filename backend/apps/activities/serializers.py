from rest_framework import serializers

from apps.activities.models import Activity, FollowUp, Notification, ReminderType
from apps.activities.services import ActivityService, FollowUpService


class ActivitySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.username", read_only=True)
    is_outbound = serializers.BooleanField(read_only=True)

    class Meta:
        model = Activity
        fields = [
            "id",
            "lead",
            "user",
            "user_name",
            "activity_type",
            "is_outbound",
            "title",
            "notes",
            "occurred_at",
            "created_at",
        ]
        read_only_fields = ["id", "user", "user_name", "is_outbound", "created_at"]

    def validate_lead(self, value):
        user = self.context["request"].user
        if user and not getattr(user, "can_view_all_leads", False):
            if value.assigned_to != user:
                raise serializers.ValidationError(
                    "Staff can only log activities on leads assigned to them."
                )
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        lead = validated_data.pop("lead")
        return ActivityService.log_activity(
            lead_id=lead.id,
            user=user,
            activity_type=validated_data.get("activity_type"),
            title=validated_data.get("title", ""),
            notes=validated_data.get("notes", ""),
            occurred_at=validated_data.get("occurred_at"),
        )


class FollowUpSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source="assigned_to.username", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = FollowUp
        fields = [
            "id",
            "lead",
            "assigned_to",
            "assigned_to_name",
            "scheduled_at",
            "status",
            "reminder_type",
            "note",
            "is_overdue",
            "completed_at",
            "completed_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "assigned_to",
            "assigned_to_name",
            "status",
            "is_overdue",
            "completed_at",
            "completed_by",
            "created_at",
            "updated_at",
        ]

    def validate_lead(self, value):
        user = self.context["request"].user
        if user and not getattr(user, "can_view_all_leads", False):
            if value.assigned_to != user:
                raise serializers.ValidationError(
                    "Staff can only schedule follow-ups on leads assigned to them."
                )
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        lead = validated_data.pop("lead")
        return FollowUpService.create_follow_up(
            lead_id=lead.id,
            scheduled_at=validated_data.get("scheduled_at"),
            reminder_type=validated_data.get("reminder_type", ReminderType.CALL),
            note=validated_data.get("note", ""),
            user=user,
        )


class CompleteFollowUpSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)
    lead_title = serializers.CharField(source="lead.title", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "user",
            "dedupe_key",
            "notification_type",
            "lead",
            "lead_title",
            "follow_up",
            "title",
            "message",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields
