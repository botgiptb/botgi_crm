import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.utils import timezone

from apps.integrations_meta.models import MetaWebhookLog, WebhookLogStatus
from apps.integrations_meta.services import MAX_WEBHOOK_ATTEMPTS, MetaLeadService

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_meta_lead_payload(self, log_id: int):
    """
    Asynchronous task to process an incoming Meta Webhook log row.
    Retries on network/timeout/5xx errors up to 3 times with exponential backoff.
    """
    try:
        MetaLeadService.process_meta_webhook_log(log_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.error("Meta webhook log #%d exhausted all retries: %s", log_id, exc)
            MetaWebhookLog.objects.filter(pk=log_id).update(
                status=WebhookLogStatus.ERROR,
                error_message=f"Retries exhausted: {str(exc)}",
                processed_at=timezone.now(),
            )
        raise exc


@shared_task
def sweep_stuck_meta_webhooks():
    """
    Periodic sweep task running every 5 minutes.
    Re-queues logs in 'received' status created more than 5 minutes ago
    that have not exceeded MAX_WEBHOOK_ATTEMPTS.
    Marks rows that exceeded attempts as error.
    """
    cutoff = timezone.now() - timedelta(minutes=5)

    # 1. Mark exhausted attempts as error
    exhausted_logs = MetaWebhookLog.objects.filter(
        status=WebhookLogStatus.RECEIVED,
        attempts__gte=MAX_WEBHOOK_ATTEMPTS,
        created_at__lt=cutoff,
    )
    exhausted_count = exhausted_logs.update(
        status=WebhookLogStatus.ERROR,
        error_message="Retries exhausted (sweep marked as error)",
        processed_at=timezone.now(),
    )
    if exhausted_count:
        logger.info("Sweep marked %d exhausted Meta webhook logs as error", exhausted_count)

    # 2. Re-queue stuck logs
    stuck_logs = MetaWebhookLog.objects.filter(
        status=WebhookLogStatus.RECEIVED,
        attempts__lt=MAX_WEBHOOK_ATTEMPTS,
        created_at__lt=cutoff,
    )
    requeued_count = 0
    for log in stuck_logs:
        process_meta_lead_payload.delay(log.id)
        requeued_count += 1

    if requeued_count:
        logger.info("Sweep re-queued %d stuck Meta webhook logs", requeued_count)

    return {"requeued": requeued_count, "exhausted": exhausted_count}


@shared_task
def cleanup_old_meta_webhook_logs():
    """
    Retention task: deletes MetaWebhookLog records older than 90 days.
    Runs daily.
    """
    cutoff = timezone.now() - timedelta(days=90)
    deleted_count, _ = MetaWebhookLog.objects.filter(created_at__lt=cutoff).delete()
    logger.info("Deleted %d MetaWebhookLog rows older than 90 days", deleted_count)
    return deleted_count
