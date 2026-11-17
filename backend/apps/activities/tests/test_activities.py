from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService
from apps.activities.models import ActivityType, FollowUp, FollowUpStatus, ReminderType
from apps.activities.services import ActivityService, FollowUpService
from apps.leads.services import LeadService


@pytest.mark.django_db
class TestActivityAndFollowUp:
    def setup_method(self):
        self.admin = UserService.create_user(
            username="admin_user",
            email="admin@example.com",
            password="Password123",
            role=User.Role.ADMIN,
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

        res1 = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Activity Test Client"},
            lead_data={"title": "PC Build Inquiry"},
            user=self.staff1,
        )
        self.lead = res1["lead"]

    def test_log_activity_updates_timestamps(self):
        assert self.lead.first_contacted_at is None
        assert self.lead.last_activity_at is None

        # 1. Log an internal note (non-outbound)
        now = timezone.now()
        ActivityService.log_activity(
            lead_id=self.lead.id,
            user=self.staff1,
            activity_type=ActivityType.NOTE,
            title="Internal review",
            notes="Checked stock for RTX 4070",
            occurred_at=now,
        )
        self.lead.refresh_from_db()
        assert self.lead.last_activity_at == now
        assert self.lead.first_contacted_at is None  # Note is not outbound!

        # 2. Log a call (outbound)
        later = now + timedelta(minutes=10)
        ActivityService.log_activity(
            lead_id=self.lead.id,
            user=self.staff1,
            activity_type=ActivityType.CALL,
            title="Called customer",
            notes="Discussed PC specifications",
            occurred_at=later,
        )
        self.lead.refresh_from_db()
        assert self.lead.last_activity_at == later
        assert self.lead.first_contacted_at == later  # First outbound contact recorded!

        # 3. Log another outbound activity; first_contacted_at remains original
        even_later = later + timedelta(hours=1)
        ActivityService.log_activity(
            lead_id=self.lead.id,
            user=self.staff1,
            activity_type=ActivityType.WHATSAPP,
            title="Sent quote via WhatsApp",
            occurred_at=even_later,
        )
        self.lead.refresh_from_db()
        assert self.lead.last_activity_at == even_later
        assert self.lead.first_contacted_at == later

    def test_follow_up_overdue_queryset(self):
        now = timezone.now()

        # Overdue pending item
        fup_overdue = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=now - timedelta(days=1),
            status=FollowUpStatus.PENDING,
            note="Past reminder",
        )
        # Upcoming pending item
        fup_upcoming = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=now + timedelta(days=2),
            status=FollowUpStatus.PENDING,
            note="Future reminder",
        )
        # Completed past item
        fup_completed = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=now - timedelta(hours=5),
            status=FollowUpStatus.COMPLETED,
            note="Already done",
        )

        overdue_items = FollowUp.objects.overdue()
        assert fup_overdue in overdue_items
        assert fup_upcoming not in overdue_items
        assert fup_completed not in overdue_items

        assert fup_overdue.is_overdue is True
        assert fup_upcoming.is_overdue is False
        assert fup_completed.is_overdue is False

    def test_complete_and_cancel_follow_up(self):
        fup = FollowUpService.create_follow_up(
            lead_id=self.lead.id,
            scheduled_at=timezone.now() + timedelta(days=1),
            reminder_type=ReminderType.CALL,
            note="Follow up on quotation",
            user=self.staff1,
        )
        assert fup.status == FollowUpStatus.PENDING

        completed = FollowUpService.complete_follow_up(
            follow_up_id=fup.id,
            user=self.staff1,
            note="Customer requested discount",
        )
        assert completed.status == FollowUpStatus.COMPLETED
        assert completed.completed_by == self.staff1
        assert completed.completed_at is not None

    def test_activities_and_follow_ups_scoping_on_endpoints(self):
        client = APIClient()

        # Lead for staff2
        res2 = LeadService.create_lead(
            customer_data={"phone": "9876543211", "name": "Staff2 Customer"},
            lead_data={"title": "Staff2 Lead"},
            user=self.staff2,
        )
        lead2 = res2["lead"]

        act1 = ActivityService.log_activity(
            lead_id=self.lead.id, user=self.staff1, activity_type=ActivityType.NOTE
        )
        act2 = ActivityService.log_activity(
            lead_id=lead2.id, user=self.staff2, activity_type=ActivityType.NOTE
        )

        # Staff1 requests activities
        client.force_authenticate(user=self.staff1)
        res = client.get("/api/activities/")
        assert res.status_code == status.HTTP_200_OK
        ids = [a["id"] for a in res.data["results"]]
        assert act1.id in ids
        assert act2.id not in ids

        # Staff1 overdue follow-ups
        fup1 = FollowUp.objects.create(
            lead=self.lead,
            assigned_to=self.staff1,
            scheduled_at=timezone.now() - timedelta(hours=2),
            status=FollowUpStatus.PENDING,
        )
        fup2 = FollowUp.objects.create(
            lead=lead2,
            assigned_to=self.staff2,
            scheduled_at=timezone.now() - timedelta(hours=2),
            status=FollowUpStatus.PENDING,
        )

        res_overdue = client.get("/api/follow-ups/overdue/")
        assert res_overdue.status_code == status.HTTP_200_OK
        fup_ids = [f["id"] for f in res_overdue.data]
        assert fup1.id in fup_ids
        assert fup2.id not in fup_ids
