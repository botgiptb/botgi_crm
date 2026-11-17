from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService
from apps.leads.models import Lead, Stage
from apps.leads.services import (
    CustomerService,
    LeadService,
    LeadStageService,
    normalize_phone_number,
)


@pytest.mark.django_db
class TestCustomerModelAndServices:
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

    def test_phone_normalization_formats(self):
        # 10 digits default region IN (+91)
        assert normalize_phone_number("9876543210") == "+919876543210"
        # formatted with spaces
        assert normalize_phone_number("+91 98765 43210") == "+919876543210"
        # formatted with dashes
        assert normalize_phone_number("098765-43210") == "+919876543210"

    def test_phone_format_variants_resolve_to_same_customer(self):
        c1, created1 = CustomerService.get_or_create_customer(
            phone="9876543210",
            name="Rahul Sharma",
            email="rahul@example.com",
        )
        assert created1 is True

        c2, created2 = CustomerService.get_or_create_customer(
            phone="+91 98765 43210",
            name="Rahul Sharma",
        )
        assert created2 is False
        assert c1.id == c2.id

    def test_one_customer_for_multiple_leads(self):
        res1 = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Rahul Sharma"},
            lead_data={"title": "Gaming PC Inquiry"},
            user=self.staff1,
        )
        res2 = LeadService.create_lead(
            customer_data={"phone": "+91 9876543210", "name": "Rahul Sharma"},
            lead_data={"title": "Laptop Purchase"},
            user=self.staff1,
        )

        lead1 = res1["lead"]
        lead2 = res2["lead"]
        assert lead1.customer_id == lead2.customer_id
        assert lead1.customer.leads.count() == 2

    def test_derived_spend_and_last_purchase_from_won_leads(self):
        customer, _ = CustomerService.get_or_create_customer(
            phone="+919876543210",
            name="VIP Client",
        )
        stage_won = Stage.objects.get(slug="won")
        stage_new = Stage.objects.get(slug="new")

        lead1 = Lead.objects.create(
            customer=customer,
            stage=stage_new,
            title="Lead 1",
        )
        lead2 = Lead.objects.create(
            customer=customer,
            stage=stage_new,
            title="Lead 2",
        )

        LeadStageService.change_stage(
            lead_id=lead1.id,
            to_stage=stage_won,
            user=self.admin,
            deal_value=Decimal("45000.00"),
        )
        LeadStageService.change_stage(
            lead_id=lead2.id,
            to_stage=stage_won,
            user=self.admin,
            deal_value=Decimal("55000.00"),
        )

        customer.refresh_from_db()
        assert customer.total_spend == Decimal("100000.00")
        assert customer.last_purchase_at is not None

    def test_protect_on_customer_delete_with_leads(self):
        res = LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Protected Client"},
            lead_data={"title": "Desktop Build"},
            user=self.staff1,
        )
        customer = res["lead"].customer
        with pytest.raises(ProtectedError):
            customer.delete()

    def test_customer_visibility_for_staff(self):
        client = APIClient()

        # Create lead for staff1
        LeadService.create_lead(
            customer_data={"phone": "9876543210", "name": "Staff1 Customer"},
            lead_data={"title": "Inquiry 1"},
            user=self.staff1,
        )
        # Create lead for staff2
        LeadService.create_lead(
            customer_data={"phone": "9876543211", "name": "Staff2 Customer"},
            lead_data={"title": "Inquiry 2"},
            user=self.staff2,
        )

        # Staff1 can only see Staff1 Customer
        client.force_authenticate(user=self.staff1)
        response = client.get("/api/customers/")
        assert response.status_code == status.HTTP_200_OK
        names = [c["name"] for c in response.data["results"]]
        assert "Staff1 Customer" in names
        assert "Staff2 Customer" not in names

        # Admin can see all customers
        client.force_authenticate(user=self.admin)
        response_admin = client.get("/api/customers/")
        assert response_admin.status_code == status.HTTP_200_OK
        admin_names = [c["name"] for c in response_admin.data["results"]]
        assert "Staff1 Customer" in admin_names
        assert "Staff2 Customer" in admin_names

    def test_only_manager_admin_can_change_customer_phone_or_deactivate(self):
        customer, _ = CustomerService.get_or_create_customer(
            phone="+919876543210",
            name="Modifiable Customer",
        )

        # Staff attempt phone change raises ValidationError
        with pytest.raises(ValidationError):
            CustomerService.update_customer(
                customer,
                user=self.staff1,
                phone="+919999988888",
            )

        # Manager/Admin succeeds
        updated = CustomerService.update_customer(
            customer,
            user=self.admin,
            phone="+919999988888",
        )
        assert updated.phone == "+919999988888"
