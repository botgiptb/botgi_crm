from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.leads.models import Customer, Lead, LeadSource, ProductCategory, Stage


@pytest.fixture
def p5a_setup(db):
    admin = User.objects.create_user(
        username="p5a_admin",
        email="p5a_admin@example.com",
        password="Pass123!Admin",
        role=User.Role.ADMIN,
    )
    manager = User.objects.create_user(
        username="p5a_manager",
        email="p5a_manager@example.com",
        password="Pass123!Manager",
        role=User.Role.MANAGER,
    )
    staff1 = User.objects.create_user(
        username="p5a_staff1",
        email="p5a_staff1@example.com",
        password="Pass123!Staff1",
        role=User.Role.STAFF,
        receives_meta_leads=True,
    )
    staff2 = User.objects.create_user(
        username="p5a_staff2",
        email="p5a_staff2@example.com",
        password="Pass123!Staff2",
        role=User.Role.STAFF,
        receives_meta_leads=False,
    )

    stage_new = Stage.objects.get_or_create(
        slug="new",
        defaults={"name": "New", "order": 0, "is_won": False, "is_lost": False},
    )[0]
    stage_quoted = Stage.objects.get_or_create(
        slug="quoted",
        defaults={"name": "Quoted", "order": 2, "is_won": False, "is_lost": False},
    )[0]
    stage_won = Stage.objects.get_or_create(
        slug="won",
        defaults={"name": "Won", "order": 4, "is_won": True, "is_lost": False},
    )[0]

    # Customer 1 with an open lead assigned to staff1
    cust1 = Customer.objects.create(
        name="Vikram Verma",
        phone="+919876543210",
        email="vikram@example.com",
        created_by=manager,
    )
    lead1 = Lead.objects.create(
        customer=cust1,
        title="Gaming Rig",
        source=LeadSource.WALK_IN,
        stage=stage_quoted,
        assigned_to=staff1,
        deal_value=Decimal("150000"),
        created_by=manager,
    )

    # Customer 2 with an open lead assigned to staff2
    cust2 = Customer.objects.create(
        name="Ananya Sharma",
        phone="+919876543211",
        email="ananya@example.com",
        created_by=manager,
    )
    lead2 = Lead.objects.create(
        customer=cust2,
        title="MacBook Pro",
        source=LeadSource.PHONE,
        stage=stage_new,
        assigned_to=staff2,
        deal_value=Decimal("200000"),
        created_by=manager,
    )

    return {
        "admin": admin,
        "manager": manager,
        "staff1": staff1,
        "staff2": staff2,
        "stage_new": stage_new,
        "stage_quoted": stage_quoted,
        "stage_won": stage_won,
        "cust1": cust1,
        "cust2": cust2,
        "lead1": lead1,
        "lead2": lead2,
    }


@pytest.mark.django_db
class TestPhase5aBackendGaps:
    """Tests for Phase 5a backend requirements: check-phone, scoping, pagination, and filters."""

    def test_check_phone_staff_gets_limited_info_only(self, p5a_setup):
        """Staff caller gets ONLY customer id/name, open lead stages & assignees (no phone, email, notes)."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["staff1"])

        # Staff1 checks customer 2 (whose lead is assigned to staff2)
        resp = client.post(
            "/api/leads/check-phone/",
            {"phone": "+919876543211"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.data
        assert data["exists"] is True

        # Customer data contains ONLY id and name
        cust = data["customer"]
        assert cust["id"] == p5a_setup["cust2"].id
        assert cust["name"] == "Ananya Sharma"
        assert "phone" not in cust
        assert "email" not in cust
        assert "total_spend" not in cust

        # Open leads contain limited fields
        assert len(data["open_leads"]) == 1
        open_lead = data["open_leads"][0]
        assert open_lead["stage_name"] == "New"
        assert open_lead["assigned_to_name"] == "p5a_staff2"
        assert open_lead["is_assigned_to_me"] is False
        assert "deal_value" not in open_lead
        assert "notes" not in open_lead

    def test_check_phone_manager_gets_full_info(self, p5a_setup):
        """Manager caller gets full customer profile, contact details, total spend, and open lead deal values."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["manager"])

        resp = client.post(
            "/api/leads/check-phone/",
            {"phone": "+919876543210"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.data
        assert data["exists"] is True

        # Customer details complete
        cust = data["customer"]
        assert cust["id"] == p5a_setup["cust1"].id
        assert cust["name"] == "Vikram Verma"
        assert cust["phone"] == "+919876543210"
        assert cust["email"] == "vikram@example.com"
        assert "total_spend" in cust

        # Lead details complete
        assert len(data["open_leads"]) == 1
        open_lead = data["open_leads"][0]
        assert open_lead["title"] == "Gaming Rig"
        assert open_lead["stage_name"] == "Quoted"
        assert open_lead["assigned_to_name"] == "p5a_staff1"
        assert open_lead["deal_value"] == "150000.00"

    def test_check_phone_nonexistent_and_invalid(self, p5a_setup):
        """Nonexistent phone returns exists=False; empty or invalid phone returns 400."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["staff1"])

        # Nonexistent phone
        resp_404 = client.post(
            "/api/leads/check-phone/",
            {"phone": "+919999900000"},
            format="json",
        )
        assert resp_404.status_code == status.HTTP_200_OK
        assert resp_404.data["exists"] is False
        assert resp_404.data["customer"] is None
        assert resp_404.data["open_leads"] == []

        # Empty phone
        resp_empty = client.post(
            "/api/leads/check-phone/",
            {"phone": ""},
            format="json",
        )
        assert resp_empty.status_code == status.HTTP_400_BAD_REQUEST

    def test_check_phone_throttling(self, p5a_setup):
        """Check-phone endpoint throttles excessive requests per user (20/min)."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["staff1"])
        cache.clear()

        # Send 20 requests
        for _ in range(20):
            res = client.post(
                "/api/leads/check-phone/",
                {"phone": "+919876543210"},
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK

        # 21st request triggers 429
        throttled = client.post(
            "/api/leads/check-phone/",
            {"phone": "+919876543210"},
            format="json",
        )
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_staff_forced_to_assigned_leads_even_with_query_param(self, p5a_setup):
        """Staff querying /api/leads/?assigned_to=<other> is strictly forced to their own leads."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["staff1"])

        # Staff1 requests leads with assigned_to=staff2's id
        staff2_id = p5a_setup["staff2"].id
        resp = client.get(f"/api/leads/?assigned_to={staff2_id}")
        assert resp.status_code == status.HTTP_200_OK

        results = resp.data["results"]
        # Must return ONLY staff1's leads
        assert len(results) == 1
        assert results[0]["id"] == p5a_setup["lead1"].id
        assert results[0]["assigned_to"] == p5a_setup["staff1"].id

    def test_manager_can_filter_by_assigned_to_and_unassigned(self, p5a_setup):
        """Managers can view all leads and filter by assigned_to ID or unassigned."""
        # Create unassigned lead
        unassigned_lead = Lead.objects.create(
            customer=p5a_setup["cust1"],
            title="Unassigned Inquiry",
            source=LeadSource.WHATSAPP,
            stage=p5a_setup["stage_new"],
            assigned_to=None,
        )

        client = APIClient()
        client.force_authenticate(user=p5a_setup["manager"])

        # Filter by staff2
        staff2_id = p5a_setup["staff2"].id
        resp_staff2 = client.get(f"/api/leads/?assigned_to={staff2_id}")
        assert resp_staff2.status_code == status.HTTP_200_OK
        assert len(resp_staff2.data["results"]) == 1
        assert resp_staff2.data["results"][0]["id"] == p5a_setup["lead2"].id

        # Filter by unassigned
        resp_unassigned = client.get("/api/leads/?assigned_to=unassigned")
        assert resp_unassigned.status_code == status.HTTP_200_OK
        assert len(resp_unassigned.data["results"]) == 1
        assert resp_unassigned.data["results"][0]["id"] == unassigned_lead.id

    def test_normalized_phone_search(self, p5a_setup):
        """Search query with local phone digits matches customer E.164 phone number."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["manager"])

        # Search using '9876543210' (without '+' or '91' prefix)
        resp = client.get("/api/leads/?search=9876543210")
        assert resp.status_code == status.HTTP_200_OK
        results = resp.data["results"]
        assert len(results) >= 1
        assert results[0]["customer_phone"] == "+919876543210"

        # Search with spaces in customer phone '98765 43211'
        resp_spaces = client.get("/api/leads/?search=98765 43211")
        assert resp_spaces.status_code == status.HTTP_200_OK
        assert len(resp_spaces.data["results"]) == 1
        assert resp_spaces.data["results"][0]["customer_phone"] == "+919876543211"

    def test_pagination_max_page_size_cap(self, p5a_setup):
        """Client requesting page_size > 100 has results capped at max_page_size=100."""
        # Create 110 leads
        leads = [
            Lead(
                customer=p5a_setup["cust1"],
                title=f"Batch Lead #{i}",
                source=LeadSource.WALK_IN,
                stage=p5a_setup["stage_new"],
                assigned_to=p5a_setup["staff1"],
            )
            for i in range(110)
        ]
        Lead.objects.bulk_create(leads)

        client = APIClient()
        client.force_authenticate(user=p5a_setup["staff1"])

        # Request page_size=500
        resp = client.get("/api/leads/?page_size=500")
        assert resp.status_code == status.HTTP_200_OK
        # Must be capped at max 100 results
        assert len(resp.data["results"]) == 100
        assert resp.data["count"] > 100

    def test_manual_lead_creation_rejects_meta_lead_ads_source(self, p5a_setup):
        """Direct creation of leads with source='meta_lead_ads' is rejected for staff and managers."""
        client = APIClient()
        client.force_authenticate(user=p5a_setup["staff1"])

        payload = {
            "customer_name": "Cheater",
            "customer_phone": "+919999911111",
            "title": "Fake Meta Lead",
            "source": LeadSource.META_LEAD_ADS,
            "product_category": ProductCategory.LAPTOP,
        }

        resp = client.post("/api/leads/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "source" in resp.data
        assert "Manual creation" in str(resp.data["source"])
