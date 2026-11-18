from decimal import Decimal
from typing import Any

import phonenumbers
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.leads.models import (
    Customer,
    CustomerType,
    Lead,
    LeadAssignment,
    LeadSource,
    LostReasonCategory,
    Stage,
    StageHistory,
    UnprocessedMetaLead,
)


def normalize_phone_number(raw_phone: str, default_region: str = "IN") -> str:
    """Normalize a phone number to standard E.164 format (+919876543210)."""
    if not raw_phone or not str(raw_phone).strip():
        raise ValidationError({"phone": "Phone number is required."})

    cleaned = str(raw_phone).strip()
    try:
        parsed = phonenumbers.parse(cleaned, default_region)
        if not phonenumbers.is_valid_number(parsed):
            raise ValidationError({"phone": f"'{raw_phone}' is not a valid phone number."})
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError(
            {"phone": f"Unable to parse phone number '{raw_phone}': {exc}"}
        ) from exc


class CustomerService:
    """Handles customer lookup, creation, phone normalization, updates, and merges."""

    clean_phone = staticmethod(normalize_phone_number)

    @staticmethod
    @transaction.atomic
    def get_or_create_customer(
        *,
        phone: str,
        name: str,
        email: str = "",
        alt_phone: str = "",
        address: str = "",
        customer_type: str = CustomerType.INDIVIDUAL,
        company_name: str = "",
        gstin: str = "",
        notes: str = "",
        created_by=None,
    ) -> tuple[Customer, bool]:
        normalized_phone = normalize_phone_number(phone)

        customer, created = Customer.objects.get_or_create(
            phone=normalized_phone,
            defaults={
                "name": name.strip(),
                "email": email.strip().lower(),
                "alt_phone": alt_phone.strip(),
                "address": address.strip(),
                "customer_type": customer_type,
                "company_name": company_name.strip(),
                "gstin": gstin.strip().upper(),
                "notes": notes.strip(),
                "created_by": created_by,
            },
        )
        # If existing customer didn't have name or email, update them
        if not created and name and (customer.name == "Unknown Customer" or not customer.name):
            customer.name = name.strip()
            customer.save(update_fields=["name", "updated_at"])

        return customer, created

    @staticmethod
    @transaction.atomic
    def update_customer(customer: Customer, user, **fields: Any) -> Customer:
        """Update customer fields with manager permission checks for phone/status."""
        new_phone = fields.get("phone")
        if new_phone:
            normalized_new_phone = normalize_phone_number(new_phone)
            if normalized_new_phone != customer.phone:
                if not getattr(user, "can_view_all_leads", False):
                    raise ValidationError(
                        {"phone": "Only managers or admins can modify customer phone numbers."}
                    )
                if (
                    Customer.objects.filter(phone=normalized_new_phone)
                    .exclude(pk=customer.pk)
                    .exists()
                ):
                    raise ValidationError(
                        {"phone": "Another customer with this phone number already exists."}
                    )
                customer.phone = normalized_new_phone

        if "is_active" in fields and fields["is_active"] != customer.is_active:
            if not getattr(user, "can_view_all_leads", False):
                raise ValidationError(
                    {"is_active": "Only managers or admins can deactivate or reactivate customers."}
                )
            customer.is_active = fields["is_active"]

        for key in [
            "name",
            "alt_phone",
            "email",
            "address",
            "customer_type",
            "company_name",
            "gstin",
            "notes",
        ]:
            if key in fields:
                setattr(customer, key, fields[key])

        customer.save()
        return customer

    @staticmethod
    @transaction.atomic
    def merge_customers(source_customer: Customer, target_customer: Customer, user) -> Customer:
        """Merge source_customer into target_customer (Manager/Admin only)."""
        if not getattr(user, "can_view_all_leads", False):
            raise ValidationError("Only managers or admins can merge customer records.")

        if source_customer.pk == target_customer.pk:
            raise ValidationError("Cannot merge a customer into itself.")

        # Re-link all leads from source to target
        source_customer.leads.all().update(customer=target_customer)

        # Deactivate source customer
        source_customer.is_active = False
        source_customer.notes = f"{source_customer.notes}\nMerged into customer #{target_customer.id} by {user.username}."
        source_customer.save(update_fields=["is_active", "notes", "updated_at"])

        return target_customer


class LeadService:
    """Service handling lead creation, assignment logging, and updates."""

    @staticmethod
    @transaction.atomic
    def create_lead(
        *,
        customer_data: dict[str, Any],
        lead_data: dict[str, Any],
        user=None,
    ) -> dict[str, Any]:
        raw_phone = customer_data.get("phone", "")

        # Reject manual creation of Meta Lead Ads leads
        source = lead_data.get("source", LeadSource.WALK_IN)
        if (
            user is not None
            and source == LeadSource.META_LEAD_ADS
            and not lead_data.get("meta_lead_id")
        ):
            raise ValidationError(
                {"source": "Manual creation of Meta Lead Ads leads is not allowed."}
            )

        if not raw_phone or not str(raw_phone).strip():
            if source == LeadSource.META_LEAD_ADS:
                unprocessed = UnprocessedMetaLead.objects.create(
                    meta_lead_id=lead_data.get("meta_lead_id")
                    or f"meta_nophone_{timezone.now().timestamp()}",
                    campaign_name=lead_data.get("campaign_name", ""),
                    ad_id=lead_data.get("ad_id", ""),
                    form_id=lead_data.get("form_id", ""),
                    raw_payload=lead_data.get("raw_meta_data", {}),
                    review_notes="Meta lead ingested without a phone number; awaiting manager review.",
                )
                return {
                    "lead": None,
                    "unprocessed_meta_lead": unprocessed,
                    "status": "stored_for_review",
                    "existing_customer": False,
                    "open_leads_warning": [],
                }
            raise ValidationError({"phone": "Phone number is required to create a lead."})

        # Resolve or create customer
        customer_name = customer_data.get("name") or "New Inquiry"
        customer, created = CustomerService.get_or_create_customer(
            phone=raw_phone,
            name=customer_name,
            email=customer_data.get("email", ""),
            alt_phone=customer_data.get("alt_phone", ""),
            address=customer_data.get("address", ""),
            customer_type=customer_data.get("customer_type", CustomerType.INDIVIDUAL),
            company_name=customer_data.get("company_name", ""),
            gstin=customer_data.get("gstin", ""),
            notes=customer_data.get("notes", ""),
            created_by=user,
        )

        # Initial stage
        initial_stage = (
            Stage.objects.filter(slug="new").first() or Stage.objects.order_by("order").first()
        )
        if not initial_stage:
            initial_stage = Stage.objects.create(name="New", slug="new", order=0)

        # Determine assignment:
        # Staff creators default assigned_to to themselves; unassigned/Meta leads stay None for managers
        assigned_to = None
        if user and user.is_authenticated:
            if getattr(user, "is_staff_role", False):
                assigned_to = user
            elif getattr(user, "can_view_all_leads", False):
                assigned_to = lead_data.get("assigned_to", user)
        else:
            # System / webhook creation without user
            assigned_to = lead_data.get("assigned_to")

        lead = Lead.objects.create(
            customer=customer,
            title=lead_data.get("title", f"Inquiry for {customer.name}"),
            source=source,
            campaign_name=lead_data.get("campaign_name", ""),
            ad_id=lead_data.get("ad_id", ""),
            form_id=lead_data.get("form_id", ""),
            meta_lead_id=lead_data.get("meta_lead_id"),
            raw_meta_data=lead_data.get("raw_meta_data", {}),
            product_category=lead_data.get("product_category", ""),
            product_brand=lead_data.get("product_brand", ""),
            budget_min=lead_data.get("budget_min"),
            budget_max=lead_data.get("budget_max"),
            stage=initial_stage,
            assigned_to=assigned_to,
            created_by=user if user and user.is_authenticated else None,
            notes=lead_data.get("notes", ""),
        )

        # Write initial LeadAssignment row (from_user=None)
        LeadAssignment.objects.create(
            lead=lead,
            assigned_by=user if user and user.is_authenticated else None,
            from_user=None,
            to_user=assigned_to,
            reason="Initial lead assignment on creation",
        )

        # Write initial StageHistory row
        StageHistory.objects.create(
            lead=lead,
            from_stage=None,
            to_stage=initial_stage,
            user=user if user and user.is_authenticated else None,
            notes="Lead created in initial stage",
        )

        # Duplicate detection: check for existing open leads for this customer
        open_leads = customer.leads.exclude(id=lead.id).filter(
            stage__is_won=False,
            stage__is_lost=False,
            is_active=True,
        )

        open_leads_warning = []
        is_staff = (
            user
            and getattr(user, "is_staff_role", False)
            and not getattr(user, "can_view_all_leads", False)
        )

        for ol in open_leads:
            if is_staff:
                # Scoped / limited warning for staff
                assignee_name = (
                    ol.assigned_to.get_full_name() or ol.assigned_to.username
                    if ol.assigned_to
                    else "Unassigned"
                )
                open_leads_warning.append(
                    {
                        "lead_id": ol.id,
                        "stage": ol.stage.name,
                        "assigned_to": assignee_name,
                    }
                )
            else:
                # Full info for managers/admin
                open_leads_warning.append(
                    {
                        "lead_id": ol.id,
                        "title": ol.title,
                        "stage": ol.stage.name,
                        "assigned_to": ol.assigned_to.username if ol.assigned_to else "Unassigned",
                        "created_at": ol.created_at.isoformat(),
                        "product_category": ol.product_category,
                    }
                )

        return {
            "lead": lead,
            "existing_customer": not created,
            "open_leads_warning": open_leads_warning,
        }

    @staticmethod
    @transaction.atomic
    def update_lead(lead: Lead, user, validated_data: dict[str, Any]) -> Lead:
        """Update lead details, restricting assignment/stage and deactivation."""
        # assigned_to and stage are forbidden here
        validated_data.pop("assigned_to", None)
        validated_data.pop("stage", None)

        if "is_active" in validated_data and validated_data["is_active"] is False:
            if not getattr(user, "can_view_all_leads", False):
                raise ValidationError(
                    {"is_active": "Only managers or admins can deactivate leads."}
                )

        for key, value in validated_data.items():
            if hasattr(lead, key):
                setattr(lead, key, value)

        lead.full_clean()
        lead.save()
        return lead


class LeadStageService:
    """Manages atomic stage transitions, validation, and reopen logic."""

    @staticmethod
    @transaction.atomic
    def change_stage(
        *,
        lead_id: int,
        to_stage: Stage,
        user,
        deal_value: Decimal | None = None,
        lost_reason_category: str = "",
        lost_reason_notes: str = "",
        notes: str = "",
    ) -> Lead:
        """Atomically transition a lead stage, validating Won/Lost conditions."""
        lead = Lead.objects.select_for_update().get(pk=lead_id)

        # Reject same-stage transition
        if lead.stage_id == to_stage.id:
            raise ValidationError({"stage": f"Lead is already in '{to_stage.name}' stage."})

        from_stage = lead.stage

        # Check reopen condition: moving from Won/Lost to an active stage
        is_currently_closed = from_stage.is_won or from_stage.is_lost
        is_targeting_active = not to_stage.is_won and not to_stage.is_lost

        if is_currently_closed and is_targeting_active:
            if not getattr(user, "can_view_all_leads", False):
                raise ValidationError(
                    {"stage": "Only managers or admins can reopen closed (Won/Lost) leads."}
                )
            # Clear closed fields on reopen
            lead.closed_at = None
            lead.deal_value = None
            lead.lost_reason_category = ""
            lead.lost_reason_notes = ""

        # Validate Won transition
        if to_stage.is_won:
            if deal_value is None or Decimal(str(deal_value)) <= Decimal("0.00"):
                raise ValidationError(
                    {
                        "deal_value": "A valid deal value (> 0) is strictly required when marking a lead as Won."
                    }
                )
            lead.deal_value = Decimal(str(deal_value))
            lead.closed_at = timezone.now()
            # Clear any lost fields
            lead.lost_reason_category = ""
            lead.lost_reason_notes = ""

        # Validate Lost transition
        elif to_stage.is_lost:
            if not lost_reason_category:
                raise ValidationError(
                    {
                        "lost_reason_category": "A lost reason category is strictly required when marking a lead as Lost."
                    }
                )
            if lost_reason_category not in LostReasonCategory.values:
                raise ValidationError(
                    {
                        "lost_reason_category": f"Invalid lost reason category. Must be one of {LostReasonCategory.values}."
                    }
                )
            if (
                lost_reason_category == LostReasonCategory.OTHER
                and not str(lost_reason_notes).strip()
            ):
                raise ValidationError(
                    {
                        "lost_reason_notes": "Specific notes are required when lost reason is 'Other'."
                    }
                )

            lead.lost_reason_category = lost_reason_category
            lead.lost_reason_notes = str(lost_reason_notes).strip()
            lead.closed_at = timezone.now()
            lead.deal_value = None

        # Update stage
        lead.stage = to_stage
        lead.save()

        # Write StageHistory audit row
        StageHistory.objects.create(
            lead=lead,
            from_stage=from_stage,
            to_stage=to_stage,
            user=user if user and user.is_authenticated else None,
            deal_value=lead.deal_value,
            lost_reason_category=lead.lost_reason_category,
            lost_reason_notes=lead.lost_reason_notes,
            notes=notes.strip(),
        )

        return lead

    @staticmethod
    @transaction.atomic
    def update_deal_value(lead_id: int, new_deal_value: Decimal, user, reason: str = "") -> Lead:
        """Edit deal_value on a Won lead (Manager/Admin only)."""
        if not getattr(user, "can_view_all_leads", False):
            raise ValidationError(
                "Only managers or admins can modify the deal value of closed leads."
            )

        lead = Lead.objects.select_for_update().get(pk=lead_id)
        if not lead.stage.is_won:
            raise ValidationError("Deal value can only be modified for leads in the 'Won' stage.")

        if new_deal_value is None or Decimal(str(new_deal_value)) <= Decimal("0.00"):
            raise ValidationError({"deal_value": "Deal value must be greater than zero."})

        old_value = lead.deal_value
        lead.deal_value = Decimal(str(new_deal_value))
        lead.save(update_fields=["deal_value", "updated_at"])

        StageHistory.objects.create(
            lead=lead,
            from_stage=lead.stage,
            to_stage=lead.stage,
            user=user if user and user.is_authenticated else None,
            deal_value=lead.deal_value,
            notes=f"Deal value updated from ₹{old_value} to ₹{lead.deal_value}. Reason: {reason}".strip(),
        )

        return lead


class LeadAssignmentService:
    """Handles manager/admin reassignment and pending FollowUp transfer."""

    @staticmethod
    @transaction.atomic
    def reassign(*, lead_id: int, to_user, assigned_by, reason: str = "") -> Lead:
        if not getattr(assigned_by, "can_view_all_leads", False):
            raise ValidationError("Only managers or admins can reassign leads.")

        lead = Lead.objects.select_for_update().get(pk=lead_id)
        from_user = lead.assigned_to

        lead.assigned_to = to_user
        lead.save(update_fields=["assigned_to", "updated_at"])

        # Write LeadAssignment log
        LeadAssignment.objects.create(
            lead=lead,
            assigned_by=assigned_by if assigned_by and assigned_by.is_authenticated else None,
            from_user=from_user,
            to_user=to_user,
            reason=reason.strip(),
        )

        # Move all pending FollowUps to new assignee in the same transaction
        lead.follow_ups.filter(status="pending").update(assigned_to=to_user)

        return lead
