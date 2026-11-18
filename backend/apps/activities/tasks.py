from datetime import timedelta
from zoneinfo import ZoneInfo

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import (
    FollowUp,
    FollowUpStatus,
    Notification,
    NotificationType,
)
from apps.activities.services import NotificationService
from apps.leads.models import Lead


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_notification_email_task(self, notification_id: int):
    """Asynchronously send email for a notification row with its own retries."""
    try:
        notif = Notification.objects.select_related("user").get(pk=notification_id)
    except Notification.DoesNotExist:
        return

    if not notif.user or not notif.user.email or not notif.user.is_active:
        return

    send_mail(
        subject=notif.title,
        message=notif.message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notif.user.email],
        fail_silently=False,
    )


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def notify_overdue_followups(self):
    """
    Check for newly overdue follow-ups using select_for_update(skip_locked=True).
    Sends notifications to assignee (or lead assignee / managers if unassigned).
    """
    now = timezone.now()
    notified_count = 0

    with transaction.atomic():
        overdue_qs = (
            FollowUp.objects.select_for_update(of=("self",), skip_locked=True)
            .filter(
                status=FollowUpStatus.PENDING,
                scheduled_at__lt=now,
                reminder_sent_at__isnull=True,
                lead__is_active=True,
                lead__stage__is_won=False,
                lead__stage__is_lost=False,
            )
            .select_related("lead", "lead__customer", "assigned_to", "lead__assigned_to")
        )

        active_managers = list(
            User.objects.filter(is_active=True, role__in=[User.Role.MANAGER, User.Role.ADMIN])
        )

        for fup in overdue_qs:
            # Determine recipients
            recipients = []
            if fup.assigned_to and fup.assigned_to.is_active:
                recipients = [fup.assigned_to]
            elif fup.lead.assigned_to and fup.lead.assigned_to.is_active:
                recipients = [fup.lead.assigned_to]
            else:
                recipients = active_managers

            scheduled_iso = fup.scheduled_at.isoformat()
            dedupe_key = f"overdue:{fup.id}:{scheduled_iso}"
            title = f"Overdue Follow-up: {fup.lead.customer.name}"
            message = (
                f"Reminder scheduled for {fup.scheduled_at.strftime('%Y-%m-%d %H:%M UTC')} is overdue.\n"
                f"Customer: {fup.lead.customer.name} ({fup.lead.customer.phone})\n"
                f"Lead: {fup.lead.title}\n"
                f"Note: {fup.note or 'No notes provided.'}"
            )

            for user in recipients:
                NotificationService.create_notification(
                    user=user,
                    dedupe_key=dedupe_key,
                    notification_type=NotificationType.OVERDUE_FOLLOW_UP,
                    title=title,
                    message=message,
                    lead=fup.lead,
                    follow_up=fup,
                )

            # Mark reminder sent
            fup.reminder_sent_at = now
            fup.save(update_fields=["reminder_sent_at", "updated_at"])
            notified_count += 1

    return f"Processed {notified_count} overdue follow-ups."


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_daily_summary(self):
    """
    Generate role-based morning summary at 09:00 Asia/Kolkata.
    Does not send empty summaries.
    """
    tz_kolkata = ZoneInfo("Asia/Kolkata")
    now_local = timezone.localtime(timezone.now(), tz_kolkata)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    today_start_utc = today_start_local.astimezone(ZoneInfo("UTC"))
    today_end_utc = today_end_local.astimezone(ZoneInfo("UTC"))
    local_date_str = now_local.strftime("%Y-%m-%d")
    last_24h = timezone.now() - timedelta(hours=24)

    dedupe_key = f"summary:{local_date_str}"
    summaries_sent = 0

    # 1. Staff Summaries
    staff_users = User.objects.filter(is_active=True, role=User.Role.STAFF)
    for staff in staff_users:
        due_today = FollowUp.objects.filter(
            assigned_to=staff,
            status=FollowUpStatus.PENDING,
            scheduled_at__gte=today_start_utc,
            scheduled_at__lte=today_end_utc,
            lead__is_active=True,
        ).count()

        overdue_count = FollowUp.objects.filter(
            assigned_to=staff,
            status=FollowUpStatus.PENDING,
            scheduled_at__lt=timezone.now(),
            lead__is_active=True,
        ).count()

        new_leads_count = Lead.objects.filter(
            assigned_to=staff,
            is_active=True,
            created_at__gte=last_24h,
        ).count()

        # Skip empty summary
        if due_today == 0 and overdue_count == 0 and new_leads_count == 0:
            continue

        title = f"Daily Sales Summary - {local_date_str}"
        message = (
            f"Good morning {staff.first_name or staff.username},\n\n"
            f"Here is your daily sales schedule for {local_date_str}:\n"
            f"- Follow-ups Due Today: {due_today}\n"
            f"- Currently Overdue Follow-ups: {overdue_count}\n"
            f"- New Leads Assigned (last 24h): {new_leads_count}\n\n"
            f"Have a productive day!"
        )

        _, created = NotificationService.create_notification(
            user=staff,
            dedupe_key=dedupe_key,
            notification_type=NotificationType.DAILY_SUMMARY,
            title=title,
            message=message,
        )
        if created:
            summaries_sent += 1

    # 2. Manager Summaries
    manager_users = User.objects.filter(
        is_active=True, role__in=[User.Role.MANAGER, User.Role.ADMIN]
    )

    unassigned_count = Lead.objects.filter(
        is_active=True,
        assigned_to__isnull=True,
        stage__is_won=False,
        stage__is_lost=False,
    ).count()

    threshold_days = getattr(settings, "STALE_LEAD_THRESHOLD_DAYS", 3)
    stale_cutoff = timezone.now() - timedelta(days=threshold_days)
    stale_leads_count = (
        Lead.objects.filter(is_active=True, stage__is_won=False, stage__is_lost=False)
        .filter(
            models.Q(last_activity_at__lt=stale_cutoff)
            | (models.Q(last_activity_at__isnull=True) & models.Q(created_at__lt=stale_cutoff))
        )
        .exclude(
            follow_ups__status=FollowUpStatus.PENDING, follow_ups__scheduled_at__gte=timezone.now()
        )
        .count()
    )

    overdue_by_staff = list(
        FollowUp.objects.filter(
            status=FollowUpStatus.PENDING,
            scheduled_at__lt=timezone.now(),
            assigned_to__isnull=False,
            assigned_to__is_active=True,
            lead__is_active=True,
        )
        .values("assigned_to__username")
        .annotate(total=models.Count("id"))
        .order_by("-total")
    )
    total_overdue = sum(item["total"] for item in overdue_by_staff)

    # Skip empty manager summary
    if unassigned_count == 0 and stale_leads_count == 0 and total_overdue == 0:
        return f"Daily summary finished. Sent {summaries_sent} staff summaries."

    staff_breakdown_lines = [
        f"  * @{item['assigned_to__username']}: {item['total']} overdue"
        for item in overdue_by_staff
    ]
    staff_breakdown_str = "\n".join(staff_breakdown_lines) if staff_breakdown_lines else "  None"

    mgr_title = f"Manager Daily Operations Summary - {local_date_str}"
    mgr_message = (
        f"Operations Overview for {local_date_str}:\n\n"
        f"- Unassigned Leads: {unassigned_count}\n"
        f"- Stale Leads (> {threshold_days} days inactive): {stale_leads_count}\n"
        f"- Total Overdue Follow-ups: {total_overdue}\n"
        f"Staff Overdue Breakdown:\n{staff_breakdown_str}"
    )

    for manager in manager_users:
        _, created = NotificationService.create_notification(
            user=manager,
            dedupe_key=dedupe_key,
            notification_type=NotificationType.DAILY_SUMMARY,
            title=mgr_title,
            message=mgr_message,
        )
        if created:
            summaries_sent += 1

    return f"Daily summary finished. Sent {summaries_sent} total summaries."


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def check_and_flag_stale_leads(self):
    """
    Identify active open leads with no activity for N days.
    Notifies the assigned staff member only (once per stale episode via dedupe_key).
    Leads with future pending follow-ups are not considered stale.
    """
    now = timezone.now()
    threshold_days = getattr(settings, "STALE_LEAD_THRESHOLD_DAYS", 3)
    cutoff = now - timedelta(days=threshold_days)

    stale_leads = (
        Lead.objects.filter(is_active=True, stage__is_won=False, stage__is_lost=False)
        .filter(
            models.Q(last_activity_at__lt=cutoff)
            | (models.Q(last_activity_at__isnull=True) & models.Q(created_at__lt=cutoff))
        )
        .exclude(follow_ups__status=FollowUpStatus.PENDING, follow_ups__scheduled_at__gte=now)
        .select_related("assigned_to", "customer")
    )

    flagged_count = 0
    for lead in stale_leads:
        if not lead.assigned_to or not lead.assigned_to.is_active:
            continue

        last_activity_time = lead.last_activity_at or lead.created_at
        last_activity_iso = last_activity_time.isoformat() if last_activity_time else "none"
        dedupe_key = f"stale:{lead.id}:{last_activity_iso}"

        title = f"Stale Lead Alert: {lead.customer.name}"
        message = (
            f"Lead #{lead.id} ({lead.title or 'No title'}) has had no activity since {last_activity_time.strftime('%Y-%m-%d')}.\n"
            f"Customer: {lead.customer.name} ({lead.customer.phone})\n"
            f"Please reach out to the customer or schedule a follow-up."
        )

        _, created = NotificationService.create_notification(
            user=lead.assigned_to,
            dedupe_key=dedupe_key,
            notification_type=NotificationType.STALE_LEAD,
            title=title,
            message=message,
            lead=lead,
        )
        if created:
            flagged_count += 1

    return f"Flagged {flagged_count} newly stale leads."
