from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q, Sum


class CustomerType(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    BUSINESS = "business", "Business"


class LeadSource(models.TextChoices):
    WALK_IN = "walk_in", "Walk-in"
    PHONE = "phone", "Phone Call"
    WHATSAPP = "whatsapp", "WhatsApp"
    META_LEAD_ADS = "meta_lead_ads", "Meta Lead Ads"
    REFERRAL = "referral", "Referral"
    WEBSITE = "website", "Website"
    OTHER = "other", "Other"


class ProductCategory(models.TextChoices):
    LAPTOP = "laptop", "Laptop"
    DESKTOP_BUILD = "desktop_build", "Desktop / Custom PC Build"
    GAMING_PC = "gaming_pc", "Gaming PC"
    PERIPHERALS = "peripherals", "Monitor & Peripherals"
    COMPONENTS = "components", "Components & Upgrades"
    REPAIR_SERVICE = "repair_service", "Repair & Service"
    OTHER = "other", "Other"


class LostReasonCategory(models.TextChoices):
    PRICE_TOO_HIGH = "price_high", "Price Too High"
    OUT_OF_STOCK = "out_of_stock", "Product Out of Stock"
    BOUGHT_ELSEWHERE = "bought_elsewhere", "Bought Elsewhere"
    SPEC_UNAVAILABLE = "spec_unavailable", "Required Specs Unavailable"
    NO_RESPONSE = "no_response", "Customer Did Not Respond"
    INVALID_INQUIRY = "invalid_inquiry", "Spam / Invalid Inquiry"
    OTHER = "other", "Other"


class Customer(models.Model):
    """Master record for customers (individuals or business entities)."""

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=32, unique=True)
    alt_phone = models.CharField(max_length=32, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    customer_type = models.CharField(
        max_length=20,
        choices=CustomerType.choices,
        default=CustomerType.INDIVIDUAL,
    )
    company_name = models.CharField(max_length=150, blank=True, default="")
    gstin = models.CharField(max_length=20, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customers",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def total_spend(self) -> Decimal:
        """Derive lifetime revenue from Won leads."""
        result = self.leads.filter(stage__is_won=True).aggregate(total=Sum("deal_value"))[
            "total"
        ] or Decimal("0.00")
        return Decimal(result)

    @property
    def last_purchase_at(self):
        """Derive latest purchase date from Won leads."""
        last_won = (
            self.leads.filter(stage__is_won=True, closed_at__isnull=False)
            .order_by("-closed_at")
            .first()
        )
        return last_won.closed_at if last_won else None

    @property
    def open_leads_count(self) -> int:
        """Derive count of currently open leads."""
        return self.leads.filter(stage__is_won=False, stage__is_lost=False).count()


class Stage(models.Model):
    """Pipeline stages: New, Contacted, Quoted, Follow-up, Won, Lost."""

    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    order = models.PositiveIntegerField(unique=True)
    is_won = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)
    color = models.CharField(max_length=20, default="#3b82f6")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            CheckConstraint(
                condition=~(Q(is_won=True) & Q(is_lost=True)),
                name="stage_not_both_won_and_lost",
            )
        ]

    def __str__(self):
        return self.name


class Lead(models.Model):
    """Sales opportunity linked to Customer and managed through stages."""

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="leads",
    )
    title = models.CharField(max_length=200, blank=True, default="")
    source = models.CharField(
        max_length=32,
        choices=LeadSource.choices,
        default=LeadSource.WALK_IN,
        db_index=True,
    )
    campaign_name = models.CharField(max_length=255, blank=True, default="")
    ad_id = models.CharField(max_length=100, blank=True, default="")
    form_id = models.CharField(max_length=100, blank=True, default="")
    meta_lead_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    raw_meta_data = models.JSONField(default=dict, blank=True)

    # Product Interest
    product_category = models.CharField(
        max_length=64,
        choices=ProductCategory.choices,
        default=ProductCategory.OTHER,
        blank=True,
    )
    product_brand = models.CharField(max_length=100, blank=True, default="")
    budget_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Pipeline & Deal State
    stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        related_name="leads",
    )
    deal_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    lost_reason_category = models.CharField(
        max_length=50,
        choices=LostReasonCategory.choices,
        blank=True,
        default="",
    )
    lost_reason_notes = models.TextField(blank=True, default="")

    # Assignment & Creator
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_leads",
    )

    # Timestamps & Lifecycle
    first_contacted_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assigned_to", "stage"]),
            models.Index(fields=["stage", "created_at"]),
            models.Index(fields=["source", "created_at"]),
        ]

    def __str__(self):
        return f"Lead #{self.id} - {self.customer.name} ({self.stage.name})"


class StageHistory(models.Model):
    """Audit log of each stage change."""

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="stage_history",
    )
    from_stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="history_from",
    )
    to_stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        related_name="history_to",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stage_changes",
    )
    deal_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    lost_reason_category = models.CharField(max_length=50, blank=True, default="")
    lost_reason_notes = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["lead", "timestamp"]),
        ]

    def __str__(self):
        from_name = self.from_stage.name if self.from_stage else "None"
        return f"Lead #{self.lead_id}: {from_name} -> {self.to_stage.name} at {self.timestamp}"


class LeadAssignment(models.Model):
    """Audit log of lead assignments and reassignments."""

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_by_logs",
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassigned_from",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassigned_to",
    )
    reason = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["lead", "timestamp"]),
            models.Index(fields=["to_user", "timestamp"]),
        ]

    def __str__(self):
        from_name = self.from_user.username if self.from_user else "Unassigned"
        to_name = self.to_user.username if self.to_user else "Unassigned"
        return f"Lead #{self.lead_id} reassigned: {from_name} -> {to_name}"


class UnprocessedMetaLead(models.Model):
    """Store raw Meta lead ad payloads that lack phone numbers for manager review."""

    meta_lead_id = models.CharField(max_length=100, unique=True)
    campaign_name = models.CharField(max_length=255, blank=True, default="")
    ad_id = models.CharField(max_length=100, blank=True, default="")
    form_id = models.CharField(max_length=100, blank=True, default="")
    raw_payload = models.JSONField(default=dict)
    review_notes = models.TextField(blank=True, default="")
    is_resolved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"UnprocessedMetaLead #{self.meta_lead_id} (Resolved: {self.is_resolved})"
