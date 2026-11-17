from django.conf import settings
from django.db import models
from django.utils import timezone


class ActivityType(models.TextChoices):
    CALL = "call", "Phone Call"
    WHATSAPP = "whatsapp", "WhatsApp Message"
    NOTE = "note", "Internal Note"
    VISIT_WALK_IN = "visit_walk_in", "In-Store Visit"
    EMAIL = "email", "Email"
    QUOTATION_SENT = "quotation_sent", "Quotation Sent"
    SYSTEM = "system", "System Event"


class FollowUpStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class ReminderType(models.TextChoices):
    CALL = "call", "Phone Call"
    WHATSAPP = "whatsapp", "WhatsApp Message"
    QUOTE_REVIEW = "quote_review", "Quote Review"
    GENERAL = "general", "General Follow-up"


class FollowUpQuerySet(models.QuerySet):
    """Custom queryset for FollowUp with .overdue() filter."""

    def overdue(self):
        """Returns pending follow-ups whose scheduled_at is in the past."""
        return self.filter(
            status=FollowUpStatus.PENDING,
            scheduled_at__lt=timezone.now(),
        )

    def upcoming(self):
        """Returns pending follow-ups scheduled for the future."""
        return self.filter(
            status=FollowUpStatus.PENDING,
            scheduled_at__gte=timezone.now(),
        )


class Activity(models.Model):
    """Interaction log with a lead customer."""

    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        related_name="activities",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    activity_type = models.CharField(
        max_length=30,
        choices=ActivityType.choices,
        db_index=True,
    )
    title = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["lead", "occurred_at"]),
            models.Index(fields=["user", "occurred_at"]),
        ]

    def __str__(self):
        return f"Activity #{self.id} ({self.activity_type}) for Lead #{self.lead_id}"

    @property
    def is_outbound(self) -> bool:
        """Determines if the interaction represents an outbound or customer-facing touchpoint."""
        return self.activity_type in [
            ActivityType.CALL,
            ActivityType.WHATSAPP,
            ActivityType.VISIT_WALK_IN,
            ActivityType.EMAIL,
            ActivityType.QUOTATION_SENT,
        ]


class FollowUp(models.Model):
    """Scheduled task or reminder associated with a lead."""

    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        related_name="follow_ups",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="follow_ups",
    )
    scheduled_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=FollowUpStatus.choices,
        default=FollowUpStatus.PENDING,
        db_index=True,
    )
    reminder_type = models.CharField(
        max_length=30,
        choices=ReminderType.choices,
        default=ReminderType.CALL,
    )
    note = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_follow_ups",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = FollowUpQuerySet.as_manager()

    class Meta:
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["assigned_to", "status", "scheduled_at"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        return f"FollowUp #{self.id} for Lead #{self.lead_id} at {self.scheduled_at}"

    @property
    def is_overdue(self) -> bool:
        """Dynamically computed overdue flag."""
        return self.status == FollowUpStatus.PENDING and self.scheduled_at < timezone.now()
