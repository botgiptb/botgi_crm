import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService
from apps.leads.models import LeadSource, Stage, UnprocessedMetaLead
from apps.leads.services import LeadService


@pytest.mark.django_db
class TestLeadEndpointsAndPermissions:
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

        res1 = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Staff1 Customer"},
            lead_data={"title": "Staff 1 Lead", "raw_meta_data": {"secret_token": "meta123"}},
            user=self.staff1,
        )
        self.lead1 = res1["lead"]

        res2 = LeadService.create_lead(
            customer_data={"phone": "9876543211", "name": "Staff2 Customer"},
            lead_data={"title": "Staff 2 Lead"},
            user=self.staff2,
        )
        self.lead2 = res2["lead"]

    def test_staff_list_only_assigned_leads(self):
        self.client.force_authenticate(user=self.staff1)
        response = self.client.get("/api/leads/")
        assert response.status_code == status.HTTP_200_OK
        lead_ids = [item["id"] for item in response.data["results"]]
        assert self.lead1.id in lead_ids
        assert self.lead2.id not in lead_ids

    def test_manager_lists_all_leads_including_unassigned(self):
        # Create unassigned lead
        LeadService.create_lead(
            customer_data={"phone": "9876543212", "name": "Unassigned Customer"},
            lead_data={"title": "Unassigned Lead", "source": LeadSource.META_LEAD_ADS},
            user=None,
        )
        self.client.force_authenticate(user=self.manager)
        response = self.client.get("/api/leads/")
        assert response.status_code == status.HTTP_200_OK
        lead_ids = [item["id"] for item in response.data["results"]]
        assert self.lead1.id in lead_ids
        assert self.lead2.id in lead_ids
        assert len(lead_ids) >= 3

    def test_staff_cannot_view_or_edit_others_lead(self):
        self.client.force_authenticate(user=self.staff1)

        # GET detail of lead2 (assigned to staff2)
        get_response = self.client.get(f"/api/leads/{self.lead2.id}/")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

        # PATCH lead2
        patch_response = self.client.patch(
            f"/api/leads/{self.lead2.id}/",
            {"title": "Hacked Title"},
            format="json",
        )
        assert patch_response.status_code == status.HTTP_404_NOT_FOUND

    def test_staff_cannot_change_assigned_to_or_stage_directly_via_patch(self):
        self.client.force_authenticate(user=self.staff1)
        stage_won = Stage.objects.get(slug="won")

        # Try to change stage and assigned_to directly in PATCH
        response = self.client.patch(
            f"/api/leads/{self.lead1.id}/",
            {
                "title": "Legitimate Title Update",
                "stage": stage_won.id,
                "assigned_to": self.staff2.id,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        self.lead1.refresh_from_db()
        assert self.lead1.title == "Legitimate Title Update"
        # Stage and assigned_to MUST remain unchanged
        assert self.lead1.stage.slug == "new"
        assert self.lead1.assigned_to == self.staff1

    def test_staff_serializer_excludes_raw_meta_data(self):
        self.client.force_authenticate(user=self.staff1)
        response = self.client.get(f"/api/leads/{self.lead1.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert "raw_meta_data" not in response.data

        # Manager can see raw_meta_data
        self.client.force_authenticate(user=self.manager)
        response_manager = self.client.get(f"/api/leads/{self.lead1.id}/")
        assert response_manager.status_code == status.HTTP_200_OK
        assert "raw_meta_data" in response_manager.data
        assert response_manager.data["raw_meta_data"] == {"secret_token": "meta123"}

    def test_only_manager_can_deactivate_lead(self):
        self.client.force_authenticate(user=self.staff1)
        # Staff attempt to deactivate
        res_staff = self.client.patch(
            f"/api/leads/{self.lead1.id}/",
            {"is_active": False},
            format="json",
        )
        assert res_staff.status_code == status.HTTP_400_BAD_REQUEST

        # Manager deactivates
        self.client.force_authenticate(user=self.manager)
        res_mgr = self.client.patch(
            f"/api/leads/{self.lead1.id}/",
            {"is_active": False},
            format="json",
        )
        assert res_mgr.status_code == status.HTTP_200_OK
        self.lead1.refresh_from_db()
        assert self.lead1.is_active is False

    def test_nested_endpoints_scoping(self):
        # Staff1 cannot access nested actions on lead2
        self.client.force_authenticate(user=self.staff1)
        res_history = self.client.get(f"/api/leads/{self.lead2.id}/stage_history/")
        assert res_history.status_code == status.HTTP_404_NOT_FOUND

        res_assignments = self.client.get(f"/api/leads/{self.lead2.id}/assignments/")
        assert res_assignments.status_code == status.HTTP_404_NOT_FOUND

        res_activities = self.client.get(f"/api/leads/{self.lead2.id}/activities/")
        assert res_activities.status_code == status.HTTP_404_NOT_FOUND

        # Staff1 CAN access nested actions on own lead1
        res_own_history = self.client.get(f"/api/leads/{self.lead1.id}/stage_history/")
        assert res_own_history.status_code == status.HTTP_200_OK
        assert len(res_own_history.data) >= 1

    def test_action_change_stage_endpoint(self):
        self.client.force_authenticate(user=self.staff1)

        response = self.client.post(
            f"/api/leads/{self.lead1.id}/change_stage/",
            {"to_stage_slug": "contacted", "notes": "Spoke on WhatsApp"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["stage_slug"] == "contacted"

    def test_unprocessed_meta_lead_endpoints_manager_admin_only(self):
        item = UnprocessedMetaLead.objects.create(
            meta_lead_id="meta_test_999",
            campaign_name="Test Campaign",
            raw_payload={"sample": "data"},
        )

        # 1. Staff is strictly forbidden (403)
        self.client.force_authenticate(user=self.staff1)
        res_list_staff = self.client.get("/api/meta-unprocessed/")
        assert res_list_staff.status_code == status.HTTP_403_FORBIDDEN

        res_detail_staff = self.client.get(f"/api/meta-unprocessed/{item.id}/")
        assert res_detail_staff.status_code == status.HTTP_403_FORBIDDEN

        # 2. Manager has full access (200)
        self.client.force_authenticate(user=self.manager)
        res_list_mgr = self.client.get("/api/meta-unprocessed/")
        assert res_list_mgr.status_code == status.HTTP_200_OK
        assert len(res_list_mgr.data["results"]) >= 1

        # Manager can update / resolve
        res_patch_mgr = self.client.patch(
            f"/api/meta-unprocessed/{item.id}/",
            {"is_resolved": True, "review_notes": "Reviewed and resolved."},
            format="json",
        )
        assert res_patch_mgr.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.is_resolved is True
