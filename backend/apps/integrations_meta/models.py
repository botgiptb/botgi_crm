from django.db import models


class WebhookLogStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    DUPLICATE = "duplicate", "Duplicate"
    ERROR = "error", "Error"


class MetaWebhookLog(models.Model):
    """Audit log of incoming Meta Lead Ads webhook deliveries."""

    meta_lead_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=WebhookLogStatus.choices,
        default=WebhookLogStatus.RECEIVED,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meta_webhook_logs",
    )
    unprocessed_lead = models.ForeignKey(
        "leads.UnprocessedMetaLead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meta_webhook_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "attempts", "created_at"]),
        ]

    def __str__(self):
        return f"MetaWebhookLog #{self.id} ({self.meta_lead_id or 'no_id'}) - {self.status}"
