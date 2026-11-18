from rest_framework import serializers

from apps.integrations_meta.models import MetaWebhookLog


class MetaWebhookLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for auditing Meta webhook logs."""

    class Meta:
        model = MetaWebhookLog
        fields = [
            "id",
            "meta_lead_id",
            "payload",
            "status",
            "attempts",
            "error_message",
            "lead",
            "unprocessed_lead",
            "created_at",
            "processed_at",
        ]
        read_only_fields = fields
