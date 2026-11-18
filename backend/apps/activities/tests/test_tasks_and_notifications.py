from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService
from apps.activities.models import (
    FollowUp,
    FollowUpStatus,
    Notification,
    NotificationType,
)
from apps.activities.services import FollowUpService, NotificationService
from apps.activities.tasks import (
    check_and_flag_stale_leads,
    notify_overdue_followups,
    send_daily_summary,
    send_notification_email_task,
)
from apps.leads.models import Stage
from apps.leads.services import LeadService, LeadStageService


@pytest.mark.django_db(transaction=True)
class TestTasksAndNotifications:
    def setup_method(self):
        self.client = APIClient()
        self.admin = UserService.create_user(
            username="admin_user",
            email="admin@example.com",
            password="Password123",
            role=User.Role.ADMIN,
        )
        self.manager = UserService.create_user(
            username="manager_user",
            email="manager@example.com",
            password="Password123",
            role=User.Role.MANAGER,
        )
        self.staff1 = UserService.create_user(
            username="staff_1",
            email="staff1@example.com",
            password="Password123",
            role=User.Role.STAFF,
        )
        self.staff2 = UserService.create_user(
            username="staff_2",
            email="staff2@example.com",
            password="Password123",
            role=User.Role.STAFF,
        )

        res = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Task Test Client"},
            lead_data={"title": "Gaming PC Inquiry"},
            user=self.staff1,
        )
        self.lead = res["lead"]
        mail.outbox.clear()

    def test_overdue_followup_notifies_once_and_sends_email(self):
        """Item 1 & 4: Dedupe key idempotency and email sent on commit."""
        scheduled_time = timezone.now() - timedelta(hours=2)
        fup = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=scheduled_time,
            note="Urgent call back",
        )

        # 1. First execution creates notification and sends email
        notify_overdue_followups()
        fup.refresh_from_db()
        assert fup.reminder_sent_at is not None

        notifs = Notification.objects.filter(user=self.staff1, follow_up=fup)
        assert notifs.count() == 1
        assert notifs.first().notification_type == NotificationType.OVERDUE_FOLLOW_UP
        assert len(mail.outbox) == 1
        assert "Overdue Follow-up" in mail.outbox[0].subject

        # 2. Second execution must be strictly idempotent (0 duplicate notifications, 0 new emails)
        notify_overdue_followups()
        assert Notification.objects.filter(user=self.staff1, follow_up=fup).count() == 1
        assert len(mail.outbox) == 1

    def test_rescheduled_followup_resets_reminder_and_notifies_again(self):
        """Item 2: Rescheduled follow-up resets reminder_sent_at and notifies again once."""
        initial_time = timezone.now() - timedelta(hours=3)
        fup = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=initial_time,
            note="Initial schedule",
        )

        # First run notifies
        notify_overdue_followups()
        fup.refresh_from_db()
        assert fup.reminder_sent_at is not None
        assert Notification.objects.filter(user=self.staff1, follow_up=fup).count() == 1

        # Reschedule to another past time (e.g. rescheduled but customer missed again)
        new_past_time = timezone.now() - timedelta(minutes=30)
        FollowUpService.reschedule_follow_up(
            follow_up_id=fup.id,
            new_scheduled_at=new_past_time,
            note="Customer requested call after 2 hours",
        )
        fup.refresh_from_db()
        assert fup.reminder_sent_at is None  # reminder_sent_at was reset!

        # Next run notifies for the new schedule
        notify_overdue_followups()
        fup.refresh_from_db()
        assert fup.reminder_sent_at is not None

        # Two distinct notifications exist (each with their distinct scheduled_at dedupe key)
        notifs = Notification.objects.filter(user=self.staff1, follow_up=fup).order_by("created_at")
        assert notifs.count() == 2
        assert notifs[0].dedupe_key != notifs[1].dedupe_key

    def test_overdue_task_fallback_to_lead_assignee_then_managers_and_skip_closed(self):
        """Item 7: If follow_up.assigned_to is null, use lead's assignee, then managers. Skip closed/inactive."""
        # Case A: follow_up.assigned_to is None -> falls back to lead.assigned_to (staff1)
        fup_no_assignee = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=None,
            scheduled_at=timezone.now() - timedelta(hours=1),
        )
        notify_overdue_followups()
        assert Notification.objects.filter(user=self.staff1, follow_up=fup_no_assignee).exists()

        # Case B: lead has no assignee either -> falls back to managers
        unassigned_lead = LeadService.create_lead(
            customer_data={"phone": "9876543211", "name": "No Assignee Lead"},
            lead_data={"title": "Web Lead"},
            user=None,
        )["lead"]
        fup_unassigned = FollowUp.objects.create(
            lead=unassigned_lead,
            assigned_to=None,
            scheduled_at=timezone.now() - timedelta(hours=1),
        )
        notify_overdue_followups()
        assert Notification.objects.filter(user=self.manager, follow_up=fup_unassigned).exists()
        assert Notification.objects.filter(user=self.admin, follow_up=fup_unassigned).exists()

        # Case C: closed lead (Won) is skipped
        stage_won = Stage.objects.get(slug="won")
        LeadStageService.change_stage(
            lead_id=self.lead.id,
            to_stage=stage_won,
            user=self.admin,
            deal_value=50000,
        )
        fup_closed = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=timezone.now() - timedelta(hours=1),
        )
        notify_overdue_followups()
        # No notification sent for follow-up on closed lead
        assert not Notification.objects.filter(follow_up=fup_closed).exists()

    def test_stale_lead_detection_and_future_followup_exclusion(self):
        """Item 3: Stale lead notifies assignee once; future follow-up prevents staleness."""
        now = timezone.now()
        # Lead with last activity 5 days ago (> 3 days threshold)
        self.lead.created_at = now - timedelta(days=6)
        self.lead.last_activity_at = now - timedelta(days=5)
        self.lead.save()

        # 1. If lead has a future pending follow-up, it is NOT stale
        fup_future = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=now + timedelta(days=2),
            status=FollowUpStatus.PENDING,
        )
        check_and_flag_stale_leads()
        assert (
            Notification.objects.filter(
                lead=self.lead, notification_type=NotificationType.STALE_LEAD
            ).count()
            == 0
        )

        # 2. When future follow-up is completed/removed, lead is detected as stale
        fup_future.status = FollowUpStatus.COMPLETED
        fup_future.save()

        check_and_flag_stale_leads()
        stale_notifs = Notification.objects.filter(
            lead=self.lead, notification_type=NotificationType.STALE_LEAD
        )
        assert stale_notifs.count() == 1
        assert stale_notifs.first().user == self.staff1

        # 3. Running again does not duplicate notification (idempotent per stale episode)
        check_and_flag_stale_leads()
        assert (
            Notification.objects.filter(
                lead=self.lead, notification_type=NotificationType.STALE_LEAD
            ).count()
            == 1
        )

    def test_daily_summary_midnight_ist_boundaries_and_content(self):
        """Item 8 & 9: Compute boundaries in Asia/Kolkata, verify staff vs manager content, skip empty."""
        # Mock time at 23:55 IST (18:25 UTC)
        tz_kolkata = ZoneInfo("Asia/Kolkata")
        fake_now = datetime(2026, 11, 18, 23, 55, tzinfo=tz_kolkata)

        with patch("django.utils.timezone.now", return_value=fake_now):
            # 1. Currently no pending items for staff2 -> staff2 receives NO summary (Item 9)
            send_daily_summary()
            assert not Notification.objects.filter(
                user=self.staff2, notification_type=NotificationType.DAILY_SUMMARY
            ).exists()

            # 2. Add a follow-up due today IST for staff1
            FollowUp.objects.create(
                lead=self.lead,
                assigned_to=self.staff1,
                scheduled_at=fake_now - timedelta(hours=1),
                status=FollowUpStatus.PENDING,
            )

            send_daily_summary()

            # Staff1 receives staff-formatted summary
            staff1_summary = Notification.objects.filter(
                user=self.staff1, notification_type=NotificationType.DAILY_SUMMARY
            ).first()
            assert staff1_summary is not None
            assert "Follow-ups Due Today" in staff1_summary.message
            assert "Daily Sales Summary - 2026-11-18" in staff1_summary.title

            # Manager receives manager-formatted summary (overdue breakdown per staff)
            mgr_summary = Notification.objects.filter(
                user=self.manager, notification_type=NotificationType.DAILY_SUMMARY
            ).first()
            assert mgr_summary is not None
            assert "Operations Overview for 2026-11-18" in mgr_summary.message
            assert "staff_1: 1 overdue" in mgr_summary.message

    def test_notification_endpoints_and_404_scoping(self):
        """Item 10: Notification endpoints return 404 for other users' notifications."""
        notif_staff1, _ = NotificationService.create_notification(
            user=self.staff1,
            dedupe_key="test:staff1:key",
            notification_type=NotificationType.SYSTEM,
            title="Notice for Staff 1",
            message="Content for Staff 1",
        )
        notif_staff2, _ = NotificationService.create_notification(
            user=self.staff2,
            dedupe_key="test:staff2:key",
            notification_type=NotificationType.SYSTEM,
            title="Notice for Staff 2",
            message="Content for Staff 2",
        )

        self.client.force_authenticate(user=self.staff1)

        # 1. Staff 1 lists only own notifications
        res_list = self.client.get("/api/notifications/")
        assert res_list.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in res_list.data["results"]]
        assert notif_staff1.id in ids
        assert notif_staff2.id not in ids

        # 2. Staff 1 attempting to view Staff 2's notification returns 404
        res_detail = self.client.get(f"/api/notifications/{notif_staff2.id}/")
        assert res_detail.status_code == status.HTTP_404_NOT_FOUND

        # 3. Staff 1 attempting to mark Staff 2's notification read returns 404
        res_mark_read_other = self.client.post(f"/api/notifications/{notif_staff2.id}/mark_read/")
        assert res_mark_read_other.status_code == status.HTTP_404_NOT_FOUND

        # 4. Staff 1 unread count
        res_count = self.client.get("/api/notifications/unread_count/")
        assert res_count.status_code == status.HTTP_200_OK
        assert res_count.data["unread_count"] == 1

        # 5. Staff 1 marks own notification read
        res_mark_read_own = self.client.post(f"/api/notifications/{notif_staff1.id}/mark_read/")
        assert res_mark_read_own.status_code == status.HTTP_200_OK
        assert res_mark_read_own.data["is_read"] is True

        res_count_after = self.client.get("/api/notifications/unread_count/")
        assert res_count_after.data["unread_count"] == 0

    def test_email_failure_does_not_rollback_notification(self):
        """Item 4: Email sending failure does not roll back the Notification row."""
        notif, created = NotificationService.create_notification(
            user=self.staff1,
            dedupe_key="email_fail_test",
            notification_type=NotificationType.SYSTEM,
            title="Important Alert",
            message="Body message",
        )
        assert created is True
        assert Notification.objects.filter(id=notif.id).exists()

        # Simulate email failure in send_notification_email_task
        with patch(
            "apps.activities.tasks.send_mail", side_effect=Exception("SMTP Connection Error")
        ):
            with pytest.raises(Exception):
                send_notification_email_task(notif.id)

        # Notification row is still present in database!
        assert Notification.objects.filter(id=notif.id).exists()
