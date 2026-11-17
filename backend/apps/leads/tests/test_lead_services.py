from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import UserService
from apps.activities.models import FollowUp
from apps.leads.models import (
    Customer,
    LeadAssignment,
    LeadSource,
    LostReasonCategory,
    Stage,
    StageHistory,
    UnprocessedMetaLead,
)
from apps.leads.services import (
    LeadAssignmentService,
    LeadService,
    LeadStageService,
)


@pytest.mark.django_db
class TestLeadServices:
    def setup_method(self):
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
        self.stage_new = Stage.objects.get(slug="new")
        self.stage_contacted = Stage.objects.get(slug="contacted")
        self.stage_won = Stage.objects.get(slug="won")
        self.stage_lost = Stage.objects.get(slug="lost")

    def test_create_lead_assignment_logging_and_stage_history(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Custom PC Build"},
            user=self.staff1,
        )
        lead = result["lead"]
        assert lead.assigned_to == self.staff1
        assert lead.created_by == self.staff1
        assert lead.stage == self.stage_new

        # Assignment log check
        assignment = LeadAssignment.objects.filter(lead=lead).first()
        assert assignment is not None
        assert assignment.from_user is None
        assert assignment.to_user == self.staff1
        assert assignment.assigned_by == self.staff1

        # Stage history check
        history = StageHistory.objects.filter(lead=lead).first()
        assert history is not None
        assert history.from_stage is None
        assert history.to_stage == self.stage_new

    def test_meta_payload_without_phone_stored_for_review(self):
        result = LeadService.create_lead(
            customer_data={"phone": "", "name": "Facebook User"},
            lead_data={
                "source": LeadSource.META_LEAD_ADS,
                "meta_lead_id": "meta_123456789",
                "campaign_name": "Diwali Sale",
                "raw_meta_data": {"ad_id": "999", "form_id": "888"},
            },
            user=None,
        )
        assert result["status"] == "stored_for_review"
        assert result["lead"] is None
        assert Customer.objects.count() == 0

        unprocessed = UnprocessedMetaLead.objects.filter(meta_lead_id="meta_123456789").first()
        assert unprocessed is not None
        assert unprocessed.campaign_name == "Diwali Sale"
        assert unprocessed.is_resolved is False

    def test_limited_duplicate_warning_for_staff_vs_full_for_manager(self):
        # Create initial lead assigned to staff1
        LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Gaming PC", "product_category": "gaming_pc"},
            user=self.staff1,
        )

        # Staff2 enters new inquiry with same phone
        staff2_res = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Laptop"},
            user=self.staff2,
        )
        warnings = staff2_res["open_leads_warning"]
        assert len(warnings) == 1
        # Staff duplicate warning contains ONLY limited fields (lead_id, stage, assigned_to)
        assert "lead_id" in warnings[0]
        assert "stage" in warnings[0]
        assert "assigned_to" in warnings[0]
        assert "product_category" not in warnings[0]
        assert "notes" not in warnings[0]

        # Manager enters inquiry with same phone
        manager_res = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Monitor"},
            user=self.manager,
        )
        m_warnings = manager_res["open_leads_warning"]
        assert len(m_warnings) >= 1
        # Manager gets detailed info
        assert "product_category" in m_warnings[0]
        assert "title" in m_warnings[0]

    def test_change_stage_rejects_same_stage(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Test Inquiry"},
            user=self.staff1,
        )
        lead = result["lead"]

        with pytest.raises(ValidationError, match="Lead is already in 'New' stage"):
            LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=self.stage_new,
                user=self.staff1,
            )

    def test_change_stage_won_requires_deal_value(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Test Inquiry"},
            user=self.staff1,
        )
        lead = result["lead"]

        # Missing deal_value
        with pytest.raises(ValidationError):
            LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=self.stage_won,
                user=self.staff1,
                deal_value=None,
            )

        # Zero or negative deal_value
        with pytest.raises(ValidationError):
            LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=self.stage_won,
                user=self.staff1,
                deal_value=Decimal("0.00"),
            )

        # Valid deal_value
        updated = LeadStageService.change_stage(
            lead_id=lead.id,
            to_stage=self.stage_won,
            user=self.staff1,
            deal_value=Decimal("72000.00"),
        )
        assert updated.stage == self.stage_won
        assert updated.deal_value == Decimal("72000.00")
        assert updated.closed_at is not None

    def test_change_stage_lost_requires_lost_reason(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Test Inquiry"},
            user=self.staff1,
        )
        lead = result["lead"]

        # Missing lost reason category
        with pytest.raises(ValidationError):
            LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=self.stage_lost,
                user=self.staff1,
            )

        # Category is 'other' but notes are blank
        with pytest.raises(
            ValidationError, match="Specific notes are required when lost reason is 'Other'"
        ):
            LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=self.stage_lost,
                user=self.staff1,
                lost_reason_category=LostReasonCategory.OTHER,
                lost_reason_notes="",
            )

        # Valid lost reason
        updated = LeadStageService.change_stage(
            lead_id=lead.id,
            to_stage=self.stage_lost,
            user=self.staff1,
            lost_reason_category=LostReasonCategory.PRICE_TOO_HIGH,
            lost_reason_notes="Competitor offered 10% lower price",
        )
        assert updated.stage == self.stage_lost
        assert updated.lost_reason_category == LostReasonCategory.PRICE_TOO_HIGH
        assert updated.closed_at is not None

    def test_reopen_behaviour_and_staff_blocked(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Vikram Patel"},
            lead_data={"title": "Closed Won Deal"},
            user=self.manager,
        )
        lead = result["lead"]
        LeadStageService.change_stage(
            lead_id=lead.id,
            to_stage=self.stage_won,
            user=self.manager,
            deal_value=Decimal("50000.00"),
        )

        # Staff attempt to reopen must be blocked
        with pytest.raises(ValidationError, match="Only managers or admins can reopen closed"):
            LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=self.stage_contacted,
                user=self.staff1,
            )

        # Manager can reopen; clears closed_at, deal_value, lost fields
        reopened = LeadStageService.change_stage(
            lead_id=lead.id,
            to_stage=self.stage_contacted,
            user=self.manager,
        )
        assert reopened.stage == self.stage_contacted
        assert reopened.closed_at is None
        assert reopened.deal_value is None
        assert reopened.lost_reason_category == ""

    def test_deal_value_update_restricted_to_manager(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Deal Value Client"},
            lead_data={"title": "Won Lead"},
            user=self.manager,
        )
        lead = result["lead"]
        LeadStageService.change_stage(
            lead_id=lead.id,
            to_stage=self.stage_won,
            user=self.manager,
            deal_value=Decimal("50000.00"),
        )

        # Staff blocked from deal_value update
        with pytest.raises(ValidationError, match="Only managers or admins can modify"):
            LeadStageService.update_deal_value(
                lead_id=lead.id,
                new_deal_value=Decimal("60000.00"),
                user=self.staff1,
            )

        # Manager succeeds and creates StageHistory
        updated = LeadStageService.update_deal_value(
            lead_id=lead.id,
            new_deal_value=Decimal("65000.00"),
            user=self.manager,
            reason="Added premium warranty",
        )
        assert updated.deal_value == Decimal("65000.00")
        latest_history = StageHistory.objects.filter(lead=lead).order_by("-timestamp").first()
        assert latest_history.deal_value == Decimal("65000.00")
        assert "Added premium warranty" in latest_history.notes

    def test_reassign_service_and_follow_up_transfer(self):
        result = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Reassignment Client"},
            lead_data={"title": "Desktop Upgrade"},
            user=self.staff1,
        )
        lead = result["lead"]

        # Create pending follow-up assigned to staff1
        fup = FollowUp.objects.create(
            lead=lead,
            assigned_to=self.staff1,
            scheduled_at=timezone.now() + timezone.timedelta(days=1),
            note="Call customer about RAM availability",
        )

        # Staff blocked from reassigning
        with pytest.raises(ValidationError, match="Only managers or admins can reassign"):
            LeadAssignmentService.reassign(
                lead_id=lead.id,
                to_user=self.staff2,
                assigned_by=self.staff1,
            )

        # Manager reassigns to staff2
        reassigned_lead = LeadAssignmentService.reassign(
            lead_id=lead.id,
            to_user=self.staff2,
            assigned_by=self.manager,
            reason="Staff 1 on leave",
        )
        assert reassigned_lead.assigned_to == self.staff2

        # Check LeadAssignment log
        assignment = LeadAssignment.objects.filter(lead=lead).order_by("-timestamp").first()
        assert assignment.from_user == self.staff1
        assert assignment.to_user == self.staff2
        assert assignment.assigned_by == self.manager
        assert assignment.reason == "Staff 1 on leave"

        # Check FollowUp was moved to staff2
        fup.refresh_from_db()
        assert fup.assigned_to == self.staff2
