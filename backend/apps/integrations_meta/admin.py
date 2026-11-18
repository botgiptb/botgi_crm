from django.contrib import admin

from apps.integrations_meta.models import MetaWebhookLog


@admin.register(MetaWebhookLog)
class MetaWebhookLogAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "meta_lead_id",
        "status",
        "attempts",
        "lead",
        "unprocessed_lead",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["meta_lead_id", "error_message"]
    readonly_fields = ["created_at", "processed_at"]
