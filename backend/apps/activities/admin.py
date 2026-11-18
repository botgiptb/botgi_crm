from django.contrib import admin

from apps.activities.models import Activity, FollowUp, Notification


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("lead", "user", "activity_type", "title", "occurred_at", "created_at")
    list_filter = ("activity_type",)
    search_fields = ("title", "notes", "lead__customer__name")


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = (
        "lead",
        "assigned_to",
        "reminder_type",
        "scheduled_at",
        "status",
        "reminder_sent_at",
    )
    list_filter = ("status", "reminder_type")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "dedupe_key", "title", "read_at", "created_at")
    list_filter = ("notification_type",)
    search_fields = ("title", "message", "dedupe_key", "user__username")
