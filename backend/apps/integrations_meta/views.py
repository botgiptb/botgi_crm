import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.accounts.permissions import IsManagerOrAdmin
from apps.integrations_meta.models import MetaWebhookLog, WebhookLogStatus
from apps.integrations_meta.serializers import MetaWebhookLogSerializer
from apps.integrations_meta.services import MetaSecurityService
from apps.integrations_meta.tasks import process_meta_lead_payload

logger = logging.getLogger(__name__)


class MetaWebhookRateThrottle(AnonRateThrottle):
    """Generous throttle for incoming Meta webhooks."""

    rate = "300/min"


@method_decorator(csrf_exempt, name="dispatch")
class MetaWebhookView(View):
    """
    Public webhook endpoint for Meta Lead Ads verification and delivery.
    CSRF exempt, unauthenticated, throttled, payload size capped, fail-closed signature check.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def dispatch(self, request, *args, **kwargs):
        # 1. Payload size check on CONTENT_LENGTH before reading body
        content_length = request.META.get("CONTENT_LENGTH")
        max_bytes = getattr(settings, "META_WEBHOOK_MAX_BYTES", 1024 * 1024)
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    return HttpResponse("Payload too large", status=413)
            except (ValueError, TypeError):
                pass

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Webhook verification handshake."""
        hub_mode = request.GET.get("hub.mode")
        verify_token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if hub_mode == "subscribe" and MetaSecurityService.verify_hub_token(verify_token):
            return HttpResponse(challenge or "", content_type="text/plain", status=200)

        return HttpResponseForbidden("Verification token invalid or missing")

    def post(self, request, *args, **kwargs):
        """Ingest incoming Meta webhook payload with fail-closed HMAC signature verification."""
        # Check body size if reading raw bytes
        max_bytes = getattr(settings, "META_WEBHOOK_MAX_BYTES", 1024 * 1024)
        raw_body = request.body
        if len(raw_body) > max_bytes:
            return HttpResponse("Payload too large", status=413)

        # Fail closed: reject if secret unset
        if not getattr(settings, "META_APP_SECRET", ""):
            logger.error("Rejecting Meta POST webhook: META_APP_SECRET is not configured.")
            return HttpResponseForbidden("Meta integration is not configured")

        # Verify signature
        sig_header = request.headers.get("X-Hub-Signature-256") or request.META.get(
            "HTTP_X_HUB_SIGNATURE_256"
        )
        if not MetaSecurityService.verify_signature(raw_body, sig_header):
            client_ip = MetaSecurityService.get_client_ip(request)
            logger.warning("Invalid Meta webhook signature from %s", client_ip)
            return HttpResponseForbidden("Invalid webhook signature")

        # Parse JSON
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return HttpResponseBadRequest("Invalid JSON")

        # Filter: only process object == 'page'
        if data.get("object") != "page":
            return HttpResponse("Non-page object ignored", status=200)

        entries = data.get("entry", [])
        configured_page_id = getattr(settings, "META_PAGE_ID", None)

        enqueued_logs = []
        for entry in entries:
            page_id = str(entry.get("id", ""))
            if configured_page_id and page_id and page_id != str(configured_page_id):
                logger.info("Ignoring webhook for unconfigured page_id: %s", page_id)
                continue

            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    val = change.get("value", {})
                    leadgen_id = str(val.get("leadgen_id") or val.get("id") or "")

                    with transaction.atomic():
                        log = MetaWebhookLog.objects.create(
                            meta_lead_id=leadgen_id,
                            payload=val,
                            status=WebhookLogStatus.RECEIVED,
                        )
                        enqueued_logs.append(log)
                        transaction.on_commit(
                            lambda l_id=log.id: process_meta_lead_payload.delay(l_id)
                        )

        if not enqueued_logs:
            return HttpResponse("No leadgen changes to process", status=200)

        return JsonResponse({"status": "ok", "enqueued": len(enqueued_logs)}, status=200)


class MetaWebhookLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Manager/Admin-only audit endpoints for Meta webhook delivery logs.
    """

    permission_classes = [IsManagerOrAdmin]
    serializer_class = MetaWebhookLogSerializer

    def get_queryset(self):
        qs = MetaWebhookLog.objects.all().order_by("-created_at")
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        meta_id = self.request.query_params.get("meta_lead_id")
        if meta_id:
            qs = qs.filter(meta_lead_id=meta_id)
        return qs

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Manually re-queue a webhook log for processing."""
        log = self.get_object()
        log.status = WebhookLogStatus.RECEIVED
        log.error_message = ""
        log.save(update_fields=["status", "error_message"])

        process_meta_lead_payload.delay(log.id)
        return Response(
            {"status": "requeued", "log_id": log.id},
            status=status.HTTP_200_OK,
        )
