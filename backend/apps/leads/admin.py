from django.contrib import admin

from apps.leads.models import (
    Customer,
    Lead,
    LeadAssignment,
    Stage,
    StageHistory,
    UnprocessedMetaLead,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "customer_type", "is_active", "created_at")
    search_fields = ("name", "phone", "email", "company_name")
    list_filter = ("customer_type", "is_active")


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order", "is_won", "is_lost", "color")
    list_editable = ("order", "color")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "stage",
        "assigned_to",
        "source",
        "product_category",
        "deal_value",
        "is_active",
        "created_at",
    )
    list_filter = ("stage", "source", "product_category", "is_active")
    search_fields = ("customer__name", "customer__phone", "title", "meta_lead_id")


@admin.register(StageHistory)
class StageHistoryAdmin(admin.ModelAdmin):
    list_display = ("lead", "from_stage", "to_stage", "user", "deal_value", "timestamp")
    list_filter = ("to_stage", "from_stage")


@admin.register(LeadAssignment)
class LeadAssignmentAdmin(admin.ModelAdmin):
    list_display = ("lead", "from_user", "to_user", "assigned_by", "timestamp")


@admin.register(UnprocessedMetaLead)
class UnprocessedMetaLeadAdmin(admin.ModelAdmin):
    list_display = ("meta_lead_id", "campaign_name", "is_resolved", "created_at")
    list_filter = ("is_resolved",)
