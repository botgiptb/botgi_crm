from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.activities.models import Activity, ActivityType, FollowUp, FollowUpStatus, ReminderType
from apps.leads.models import Lead


class ActivityService:
    """Service handling activity logging and updating lead engagement metrics."""

    @staticmethod
    @transaction.atomic
    def log_activity(
        *,
        lead_id: int,
        user,
        activity_type: str,
        title: str = "",
        notes: str = "",
        occurred_at: datetime | None = None,
    ) -> Activity:
        if activity_type not in ActivityType.values:
            raise ValidationError({"activity_type": f"Invalid activity type: {activity_type}."})

        lead = Lead.objects.select_for_update().get(pk=lead_id)
        if user and user.is_authenticated and not getattr(user, "can_view_all_leads", False):
            if lead.assigned_to != user:
                raise ValidationError(
                    {"lead": "Staff can only log activities on leads assigned to them."}
                )
        effective_time = occurred_at or timezone.now()

        activity = Activity.objects.create(
            lead=lead,
            user=user if user and user.is_authenticated else None,
            activity_type=activity_type,
            title=title.strip(),
            notes=notes.strip(),
            occurred_at=effective_time,
        )

        # Update lead engagement timestamps
        lead.last_activity_at = effective_time
        if activity.is_outbound and lead.first_contacted_at is None:
            lead.first_contacted_at = effective_time

        lead.save(update_fields=["last_activity_at", "first_contacted_at", "updated_at"])
        return activity


class FollowUpService:
    """Service handling follow-up reminder scheduling, completion, and cancellation."""

    @staticmethod
    @transaction.atomic
    def create_follow_up(
        *,
        lead_id: int,
        scheduled_at: datetime,
        reminder_type: str = ReminderType.CALL,
        note: str = "",
        user=None,
        assigned_to=None,
    ) -> FollowUp:
        lead = Lead.objects.get(pk=lead_id)
        if user and user.is_authenticated and not getattr(user, "can_view_all_leads", False):
            if lead.assigned_to != user:
                raise ValidationError(
                    {"lead": "Staff can only schedule follow-ups on leads assigned to them."}
                )

        target_assignee = assigned_to or lead.assigned_to or user
        return FollowUp.objects.create(
            lead=lead,
            assigned_to=target_assignee,
            scheduled_at=scheduled_at,
            reminder_type=reminder_type,
            note=note.strip(),
        )

    @staticmethod
    @transaction.atomic
    def complete_follow_up(*, follow_up_id: int, user, note: str = "") -> FollowUp:
        follow_up = FollowUp.objects.select_for_update().get(pk=follow_up_id)
        if follow_up.status == FollowUpStatus.COMPLETED:
            raise ValidationError("This follow-up is already marked as completed.")

        follow_up.status = FollowUpStatus.COMPLETED
        follow_up.completed_at = timezone.now()
        follow_up.completed_by = user
        if note:
            follow_up.note = f"{follow_up.note}\nCompleted Note: {note}".strip()
        follow_up.save()
        return follow_up

    @staticmethod
    @transaction.atomic
    def cancel_follow_up(*, follow_up_id: int, user) -> FollowUp:
        follow_up = FollowUp.objects.select_for_update().get(pk=follow_up_id)
        follow_up.status = FollowUpStatus.CANCELLED
        follow_up.save(update_fields=["status", "updated_at"])
        return follow_up
