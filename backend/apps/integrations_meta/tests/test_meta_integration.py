import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import UserService
from apps.activities.models import Notification, NotificationType
from apps.integrations_meta.models import MetaWebhookLog, WebhookLogStatus
from apps.integrations_meta.services import MetaLeadService
from apps.integrations_meta.tasks import (
    cleanup_old_meta_webhook_logs,
    process_meta_lead_payload,
    sweep_stuck_meta_webhooks,
)
from apps.leads.models import (
    Customer,
    Lead,
    LeadSource,
    ProductCategory,
    Stage,
    UnprocessedMetaLead,
)
from apps.leads.services import LeadService

TEST_SECRET = "test_meta_secret_key_12345"
TEST_VERIFY_TOKEN = "verify_token_secure_abc123"


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def meta_users(db):
    admin = UserService.create_user(
        username="admin_meta",
        email="admin_meta@example.com",
        password="password123",
        role=User.Role.ADMIN,
    )
    manager = UserService.create_user(
        username="mgr_meta",
        email="mgr_meta@example.com",
        password="password123",
        role=User.Role.MANAGER,
    )
    staff1 = UserService.create_user(
        username="staff_meta1",
        email="staff_meta1@example.com",
        password="password123",
        role=User.Role.STAFF,
        receives_meta_leads=True,
    )
    staff2 = UserService.create_user(
        username="staff_meta2",
        email="staff_meta2@example.com",
        password="password123",
        role=User.Role.STAFF,
        receives_meta_leads=True,
    )
    staff_no_leads = UserService.create_user(
        username="staff_no_meta",
        email="staff_no_meta@example.com",
        password="password123",
        role=User.Role.STAFF,
        receives_meta_leads=False,
    )
    return {
        "admin": admin,
        "manager": manager,
        "staff1": staff1,
        "staff2": staff2,
        "staff_no_leads": staff_no_leads,
    }


@pytest.mark.django_db(transaction=True)
class TestMetaWebhookHandshakeAndSecurity:
    """Tests for GET verification handshake and POST signature security."""

    def test_verify_handshake_success(self, api_client):
        with override_settings(META_VERIFY_TOKEN=TEST_VERIFY_TOKEN):
            response = api_client.get(
                "/api/integrations/meta/webhook/",
                {
                    "hub.mode": "subscribe",
                    "hub.verify_token": TEST_VERIFY_TOKEN,
                    "hub.challenge": "challenge_code_999",
                },
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.content.decode("utf-8") == "challenge_code_999"

    def test_verify_handshake_invalid_or_missing_token(self, api_client):
        with override_settings(META_VERIFY_TOKEN=TEST_VERIFY_TOKEN):
            # Wrong token
            resp = api_client.get(
                "/api/integrations/meta/webhook/",
                {
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong_token",
                    "hub.challenge": "123",
                },
            )
            assert resp.status_code == status.HTTP_403_FORBIDDEN

            # Wrong mode
            resp = api_client.get(
                "/api/integrations/meta/webhook/",
                {
                    "hub.mode": "publish",
                    "hub.verify_token": TEST_VERIFY_TOKEN,
                    "hub.challenge": "123",
                },
            )
            assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_verify_handshake_when_secret_unset(self, api_client):
        with override_settings(META_VERIFY_TOKEN=""):
            resp = api_client.get(
                "/api/integrations/meta/webhook/",
                {
                    "hub.mode": "subscribe",
                    "hub.verify_token": "any",
                    "hub.challenge": "123",
                },
            )
            assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_post_fails_closed_when_app_secret_unset(self, api_client):
        payload = b'{"object": "page"}'
        with override_settings(META_APP_SECRET=""):
            response = api_client.post(
                "/api/integrations/meta/webhook/",
                data=payload,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256="sha256=invalid",
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_post_rejects_missing_or_bad_signature(self, api_client):
        payload = b'{"object": "page"}'
        with override_settings(META_APP_SECRET=TEST_SECRET):
            # Missing header
            resp1 = api_client.post(
                "/api/integrations/meta/webhook/",
                data=payload,
                content_type="application/json",
            )
            assert resp1.status_code == status.HTTP_403_FORBIDDEN

            # Tampered signature
            resp2 = api_client.post(
                "/api/integrations/meta/webhook/",
                data=payload,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256="sha256=0000000000000000000000000000000000000000000000000000000000000000",
            )
            assert resp2.status_code == status.HTTP_403_FORBIDDEN

    def test_oversized_payload_returns_413(self, api_client):
        max_bytes = 100
        big_body = b"x" * 200
        with override_settings(META_APP_SECRET=TEST_SECRET, META_WEBHOOK_MAX_BYTES=max_bytes):
            sig = compute_signature(TEST_SECRET, big_body)
            # Test CONTENT_LENGTH header check
            resp = api_client.post(
                "/api/integrations/meta/webhook/",
                data=big_body,
                content_type="application/json",
                HTTP_CONTENT_LENGTH=str(len(big_body)),
                HTTP_X_HUB_SIGNATURE_256=sig,
            )
            assert resp.status_code == 413

    def test_invalid_json_returns_400(self, api_client):
        bad_json = b"not a json document"
        with override_settings(META_APP_SECRET=TEST_SECRET):
            sig = compute_signature(TEST_SECRET, bad_json)
            resp = api_client.post(
                "/api/integrations/meta/webhook/",
                data=bad_json,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=sig,
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_page_or_non_leadgen_entries_ignored(self, api_client):
        with override_settings(META_APP_SECRET=TEST_SECRET):
            # Non-page object
            user_obj_body = json.dumps({"object": "user", "entry": []}).encode("utf-8")
            resp = api_client.post(
                "/api/integrations/meta/webhook/",
                data=user_obj_body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=compute_signature(TEST_SECRET, user_obj_body),
            )
            assert resp.status_code == status.HTTP_200_OK
            assert MetaWebhookLog.objects.count() == 0

            # Page object but non-leadgen change
            feed_body = json.dumps(
                {
                    "object": "page",
                    "entry": [
                        {
                            "id": "111",
                            "changes": [{"field": "feed", "value": {"item": "status"}}],
                        }
                    ],
                }
            ).encode("utf-8")
            resp2 = api_client.post(
                "/api/integrations/meta/webhook/",
                data=feed_body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=compute_signature(TEST_SECRET, feed_body),
            )
            assert resp2.status_code == status.HTTP_200_OK
            assert MetaWebhookLog.objects.count() == 0

    def test_spoofed_forwarded_for_cannot_exhaust_victim_ip_bucket(self, api_client):
        """
        Attacker spoofing client IP by prepending victim IP to X-Forwarded-For
        cannot exhaust the victim's throttle bucket.
        """
        from django.core.cache import cache

        cache.clear()
        bad_payload = b'{"object": "page"}'
        victim_ip = "203.0.113.195"
        attacker_ip = "198.51.100.4"

        with override_settings(META_APP_SECRET=TEST_SECRET, NUM_PROXIES=1):
            # Attacker sends 10 requests with invalid signature and spoofed X-Forwarded-For
            spoofed_header = f"{victim_ip}, {attacker_ip}"
            for _ in range(10):
                resp = api_client.post(
                    "/api/integrations/meta/webhook/",
                    data=bad_payload,
                    content_type="application/json",
                    HTTP_X_FORWARDED_FOR=spoofed_header,
                    HTTP_X_HUB_SIGNATURE_256="sha256=invalid_signature",
                )
                assert resp.status_code == status.HTTP_403_FORBIDDEN

            # 11th request from attacker IP is throttled
            resp_attacker_throttled = api_client.post(
                "/api/integrations/meta/webhook/",
                data=bad_payload,
                content_type="application/json",
                HTTP_X_FORWARDED_FOR=spoofed_header,
                HTTP_X_HUB_SIGNATURE_256="sha256=invalid_signature",
            )
            assert resp_attacker_throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS

            # Victim IP itself is NOT throttled (gets 403, not 429)
            resp_victim = api_client.post(
                "/api/integrations/meta/webhook/",
                data=bad_payload,
                content_type="application/json",
                HTTP_X_FORWARDED_FOR=victim_ip,
                HTTP_X_HUB_SIGNATURE_256="sha256=invalid_signature",
            )
            assert resp_victim.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db(transaction=True)
class TestMetaLeadIngestionAndProcessing:
    """Tests for payload processing, Graph API fetch, routing, and deduplication."""

    def test_mock_lead_processing_with_phone_creates_lead_and_assigns(self, meta_users):
        """Lead ad payload with phone creates Customer, Lead, and assigns to flagged staff."""
        meta_users["staff1"]
        mock_payload = {
            "leadgen_id": "meta_lead_001",
            "campaign_name": "Diwali Gaming PC Sale",
            "ad_id": "ad_123",
            "form_id": "form_456",
            "lead_data": {
                "created_time": "2026-11-18T05:00:00+0000",
                "field_data": [
                    {"name": "full_name", "values": ["Kavita Verma"]},
                    {"name": "phone_number", "values": ["p:+919876543210"]},
                    {"name": "email", "values": ["kavita@example.com"]},
                    {"name": "what_product_are_you_looking_for?", "values": ["Gaming PC build"]},
                    {"name": "budget", "values": ["70000 - 95000"]},
                ],
            },
        }

        log = MetaWebhookLog.objects.create(
            meta_lead_id="meta_lead_001",
            payload=mock_payload,
            status=WebhookLogStatus.RECEIVED,
        )

        process_meta_lead_payload(log.id)

        log.refresh_from_db()
        assert log.status == WebhookLogStatus.PROCESSED
        assert log.lead is not None
        assert log.lead.meta_lead_id == "meta_lead_001"
        assert log.lead.source == LeadSource.META_LEAD_ADS
        assert log.lead.product_category == ProductCategory.GAMING_PC
        assert log.lead.budget_min == 70000
        assert log.lead.budget_max == 95000
        assert log.lead.raw_meta_data.get("created_time") == "2026-11-18T05:00:00+0000"

        # Customer created with normalized E.164 phone
        assert log.lead.customer.phone == "+919876543210"
        assert log.lead.customer.name == "Kavita Verma"

        # Assigned to eligible staff member
        assert log.lead.assigned_to in [meta_users["staff1"], meta_users["staff2"]]

        # Notification emitted to assignee
        notif = Notification.objects.filter(
            user=log.lead.assigned_to,
            notification_type=NotificationType.NEW_LEAD,
        ).first()
        assert notif is not None
        assert "Kavita Verma" in notif.message

    def test_round_robin_assignment_distribution(self, meta_users):
        """Sequential Meta leads rotate round-robin across staff with receives_meta_leads=True."""
        staff1 = meta_users["staff1"]
        staff2 = meta_users["staff2"]

        # Lead 1
        log1 = MetaWebhookLog.objects.create(
            meta_lead_id="rr_lead_1",
            payload={
                "leadgen_id": "rr_lead_1",
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Lead One"]},
                        {"name": "phone", "values": ["+919800000001"]},
                    ]
                },
            },
        )
        process_meta_lead_payload(log1.id)
        log1.refresh_from_db()
        assignee_1 = log1.lead.assigned_to
        assert assignee_1 in (staff1, staff2)

        # Lead 2
        log2 = MetaWebhookLog.objects.create(
            meta_lead_id="rr_lead_2",
            payload={
                "leadgen_id": "rr_lead_2",
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Lead Two"]},
                        {"name": "phone", "values": ["+919800000002"]},
                    ]
                },
            },
        )
        process_meta_lead_payload(log2.id)
        log2.refresh_from_db()
        assignee_2 = log2.lead.assigned_to
        assert assignee_2 in (staff1, staff2)
        assert assignee_2 != assignee_1  # Rotated to the other staff member!

        # Lead 3 wraps around
        log3 = MetaWebhookLog.objects.create(
            meta_lead_id="rr_lead_3",
            payload={
                "leadgen_id": "rr_lead_3",
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Lead Three"]},
                        {"name": "phone", "values": ["+919800000003"]},
                    ]
                },
            },
        )
        process_meta_lead_payload(log3.id)
        log3.refresh_from_db()
        assignee_3 = log3.lead.assigned_to
        assert assignee_3 == assignee_1  # Wrapped back to first assignee

    def test_existing_customer_open_lead_affinity_routing(self, meta_users):
        """If customer already has an active open lead with an assignee, new Meta lead routes to that assignee."""
        staff1 = meta_users["staff1"]
        staff2 = meta_users["staff2"]

        # Staff2 has more recent assignment than staff1
        staff1.last_meta_lead_assigned_at = timezone.now() - timedelta(hours=2)
        staff1.save()
        staff2.last_meta_lead_assigned_at = timezone.now() - timedelta(hours=1)
        staff2.save()

        # Customer already exists with open lead assigned to staff2
        customer = Customer.objects.create(name="Existing Customer", phone="+919888877777")
        stage_new = Stage.objects.get(slug="new")
        Lead.objects.create(
            customer=customer,
            title="Old Open Lead",
            stage=stage_new,
            assigned_to=staff2,
            is_active=True,
        )

        # Incoming Meta lead for this existing customer
        log = MetaWebhookLog.objects.create(
            meta_lead_id="affinity_lead_01",
            payload={
                "leadgen_id": "affinity_lead_01",
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Existing Customer"]},
                        {"name": "phone", "values": ["+919888877777"]},
                    ]
                },
            },
        )
        process_meta_lead_payload(log.id)
        log.refresh_from_db()

        # Even though staff1 had oldest last_meta_lead_assigned_at, lead routed to staff2 due to customer affinity!
        assert log.lead.assigned_to == staff2

    def test_no_phone_payload_routes_to_unprocessed_and_notifies_managers(self, meta_users):
        """Payload lacking a phone number creates UnprocessedMetaLead and notifies managers."""
        log = MetaWebhookLog.objects.create(
            meta_lead_id="no_phone_lead_99",
            payload={
                "leadgen_id": "no_phone_lead_99",
                "campaign_name": "No Phone Campaign",
                "lead_data": {
                    "field_data": [
                        {"name": "full_name", "values": ["Anonymous User"]},
                        {"name": "email", "values": ["anon@example.com"]},
                    ]
                },
            },
        )

        process_meta_lead_payload(log.id)
        log.refresh_from_db()

        assert log.status == WebhookLogStatus.PROCESSED
        assert log.unprocessed_lead is not None
        assert log.unprocessed_lead.meta_lead_id == "no_phone_lead_99"
        assert log.unprocessed_lead.campaign_name == "No Phone Campaign"
        assert log.unprocessed_lead.is_resolved is False

        # Managers notified
        mgr_notif = Notification.objects.filter(
            user=meta_users["manager"],
            notification_type=NotificationType.UNPROCESSED_META_LEAD,
        ).first()
        assert mgr_notif is not None
        assert "no_phone_lead_99" in mgr_notif.message

    def test_duplicate_delivery_is_idempotent(self, meta_users):
        """Second webhook delivery for identical meta_lead_id marks duplicate and creates no new lead."""
        payload = {
            "leadgen_id": "dupe_lead_77",
            "lead_data": {
                "field_data": [
                    {"name": "full_name", "values": ["Dupe Test"]},
                    {"name": "phone", "values": ["+919111122222"]},
                ]
            },
        }

        log1 = MetaWebhookLog.objects.create(meta_lead_id="dupe_lead_77", payload=payload)
        process_meta_lead_payload(log1.id)
        log1.refresh_from_db()
        assert log1.status == WebhookLogStatus.PROCESSED
        lead_count_initial = Lead.objects.count()

        # Duplicate delivery
        log2 = MetaWebhookLog.objects.create(meta_lead_id="dupe_lead_77", payload=payload)
        process_meta_lead_payload(log2.id)
        log2.refresh_from_db()

        assert log2.status == WebhookLogStatus.DUPLICATE
        assert log2.lead == log1.lead
        assert Lead.objects.count() == lead_count_initial

    def test_concurrent_duplicate_delivery_integrity_error(self, meta_users):
        """Simulate concurrent delivery where create_lead raises IntegrityError."""
        from django.db import IntegrityError

        payload = {
            "leadgen_id": "concurrent_dupe_lead",
            "lead_data": {
                "field_data": [
                    {"name": "full_name", "values": ["Concurrent User"]},
                    {"name": "phone", "values": ["+919222233333"]},
                ]
            },
        }

        # First lead created normally
        log1 = MetaWebhookLog.objects.create(meta_lead_id="concurrent_dupe_lead", payload=payload)
        process_meta_lead_payload(log1.id)
        log1.refresh_from_db()

        # Second delivery encounters race condition triggering IntegrityError
        log2 = MetaWebhookLog.objects.create(meta_lead_id="concurrent_dupe_lead", payload=payload)
        with patch(
            "apps.integrations_meta.services.LeadService.create_lead",
            side_effect=IntegrityError("Duplicate meta_lead_id"),
        ):
            process_meta_lead_payload(log2.id)

        log2.refresh_from_db()
        assert log2.status == WebhookLogStatus.DUPLICATE
        assert log2.lead == log1.lead

    def test_concurrent_round_robin_picks_different_staff(self, meta_users):
        """Concurrent lead assignments select different staff members without collision."""
        import concurrent.futures

        from django.db import connection

        if connection.vendor == "sqlite":
            pytest.skip(
                "SQLite file lock does not support multi-threaded concurrent write transactions."
            )

        customer1 = Customer.objects.create(name="Cust One", phone="+919000000001")
        customer2 = Customer.objects.create(name="Cust Two", phone="+919000000002")

        import time

        def assign_for_customer(cust_id, delay=0.0):
            connection.close()
            with transaction.atomic():
                cust = Customer.objects.get(id=cust_id)
                from apps.integrations_meta.services import MetaAssignmentService

                res = MetaAssignmentService.determine_lead_assignee(cust)
                if delay:
                    time.sleep(delay)
                return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(assign_for_customer, customer1.id, 0.15)
            time.sleep(0.02)  # Ensure thread 1 acquires the first lock
            future2 = executor.submit(assign_for_customer, customer2.id, 0.0)
            assignee1 = future1.result()
            assignee2 = future2.result()

        assert assignee1 is not None
        assert assignee2 is not None
        assert assignee1.id != assignee2.id

    def test_single_eligible_staff_concurrent_leads_and_non_flagged_never_picked(self, meta_users):
        """
        With exactly one eligible staff member, concurrent leads all go to that member,
        and staff with receives_meta_leads=False are never picked.
        """
        # Flag only staff1; unflag staff2 and staff_no_leads
        meta_users["staff1"].receives_meta_leads = True
        meta_users["staff1"].save()
        meta_users["staff2"].receives_meta_leads = False
        meta_users["staff2"].save()
        meta_users["staff_no_leads"].receives_meta_leads = False
        meta_users["staff_no_leads"].save()

        # Ingest Lead A
        log_a = MetaWebhookLog.objects.create(
            meta_lead_id="single_staff_lead_a",
            payload={
                "leadgen_id": "single_staff_lead_a",
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Cust A"]},
                        {"name": "phone", "values": ["+919000000010"]},
                    ]
                },
            },
        )
        process_meta_lead_payload(log_a.id)
        log_a.refresh_from_db()

        # Ingest Lead B
        log_b = MetaWebhookLog.objects.create(
            meta_lead_id="single_staff_lead_b",
            payload={
                "leadgen_id": "single_staff_lead_b",
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Cust B"]},
                        {"name": "phone", "values": ["+919000000020"]},
                    ]
                },
            },
        )
        process_meta_lead_payload(log_b.id)
        log_b.refresh_from_db()

        # Both leads must go to staff1 (the single eligible staff member)
        assert log_a.lead.assigned_to == meta_users["staff1"]
        assert log_b.lead.assigned_to == meta_users["staff1"]

        # Non-flagged staff are never picked
        assert log_a.lead.assigned_to != meta_users["staff2"]
        assert log_b.lead.assigned_to != meta_users["staff2"]
        assert log_a.lead.assigned_to != meta_users["staff_no_leads"]
        assert log_b.lead.assigned_to != meta_users["staff_no_leads"]

    @patch("requests.get")
    def test_real_webhook_fetches_lead_from_graph_api(self, mock_get, meta_users):
        """Real webhook with only leadgen_id fetches details from Meta Graph API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "graph_lead_123",
            "created_time": "2026-11-18T06:00:00+0000",
            "field_data": [
                {"name": "full_name", "values": ["Graph API Customer"]},
                {"name": "phone_number", "values": ["+919777788888"]},
            ],
        }
        mock_get.return_value = mock_response

        log = MetaWebhookLog.objects.create(
            meta_lead_id="graph_lead_123",
            payload={"leadgen_id": "graph_lead_123"},
        )

        with override_settings(
            META_PAGE_ACCESS_TOKEN="mock_page_token", META_GRAPH_VERSION="v22.0"
        ):
            process_meta_lead_payload(log.id)

        log.refresh_from_db()
        assert log.status == WebhookLogStatus.PROCESSED
        assert log.lead.customer.name == "Graph API Customer"
        assert log.lead.customer.phone == "+919777788888"

        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert "graph.facebook.com/v22.0/graph_lead_123" in called_url

    @patch("requests.get")
    def test_permanent_4xx_not_retried_and_notifies_managers(self, mock_get, meta_users):
        """Permanent 400/401 OAuth error from Graph API marks log as error and does not retry."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "error": {
                "message": "Error validating access token: Session has expired",
                "type": "OAuthException",
                "code": 190,
            }
        }
        mock_get.return_value = mock_resp

        log = MetaWebhookLog.objects.create(
            meta_lead_id="expired_token_lead",
            payload={"leadgen_id": "expired_token_lead"},
        )

        # Calling service directly catches MetaGraphPermanentError
        with override_settings(META_PAGE_ACCESS_TOKEN="expired_token"):
            process_meta_lead_payload(log.id)

        log.refresh_from_db()
        assert log.status == WebhookLogStatus.ERROR
        assert "Session has expired" in log.error_message

        # Manager notified of Graph API token error
        notif = Notification.objects.filter(
            user=meta_users["manager"],
            notification_type=NotificationType.META_API_ERROR,
        ).first()
        assert notif is not None
        assert "expired_token_lead" in notif.message

    @patch("requests.get")
    def test_failure_after_claim_leaves_attempts_incremented(self, mock_get, meta_users):
        """
        Verify that when a failure occurs during the Graph API call (outside the transaction),
        the claim transaction has already committed, leaving attempts incremented.
        """
        mock_get.side_effect = requests.exceptions.ConnectionError("Network connection reset")

        log = MetaWebhookLog.objects.create(
            meta_lead_id="transient_fail_lead_01",
            payload={"leadgen_id": "transient_fail_lead_01"},
            status=WebhookLogStatus.RECEIVED,
            attempts=0,
        )

        # First failure: attempts incremented to 1 and exception re-raised for Celery retry
        with pytest.raises(requests.exceptions.ConnectionError):
            MetaLeadService.process_meta_webhook_log(log.id)

        log.refresh_from_db()
        assert log.attempts == 1
        assert log.status == WebhookLogStatus.RECEIVED  # Still received, waiting for retry

        # Second failure: attempts incremented to 2
        with pytest.raises(requests.exceptions.ConnectionError):
            MetaLeadService.process_meta_webhook_log(log.id)

        log.refresh_from_db()
        assert log.attempts == 2

        # Third failure: attempts reaches 3 (MAX_WEBHOOK_ATTEMPTS), marked as ERROR
        MetaLeadService.process_meta_webhook_log(log.id)
        log.refresh_from_db()
        assert log.attempts == 3
        assert log.status == WebhookLogStatus.ERROR
        assert "Retries exhausted" in log.error_message


@pytest.mark.django_db(transaction=True)
class TestMetaManagerResolveAndMaintenance:
    """Tests for resolving unprocessed leads, sweep, cleanup, and permissions."""

    def test_manager_resolves_unprocessed_lead_endpoint(self, api_client, meta_users):
        """Manager resolves unprocessed lead by supplying phone via API."""
        unprocessed = UnprocessedMetaLead.objects.create(
            meta_lead_id="resolve_me_001",
            campaign_name="Diwali Sale",
            raw_payload={
                "field_data": [
                    {"name": "full_name", "values": ["Sunil Sharma"]},
                    {"name": "email", "values": ["sunil@example.com"]},
                ]
            },
        )
        log = MetaWebhookLog.objects.create(
            meta_lead_id="resolve_me_001",
            unprocessed_lead=unprocessed,
            status=WebhookLogStatus.PROCESSED,
        )

        # Staff cannot resolve (403)
        api_client.force_authenticate(user=meta_users["staff1"])
        resp_staff = api_client.post(
            f"/api/meta-unprocessed/{unprocessed.id}/resolve/",
            {"phone": "+919999988888"},
        )
        assert resp_staff.status_code == status.HTTP_403_FORBIDDEN

        # Manager resolves successfully
        api_client.force_authenticate(user=meta_users["manager"])
        resp_mgr = api_client.post(
            f"/api/meta-unprocessed/{unprocessed.id}/resolve/",
            {"phone": "+919999988888", "notes": "Resolved after phone call"},
        )
        assert resp_mgr.status_code == status.HTTP_200_OK

        unprocessed.refresh_from_db()
        assert unprocessed.is_resolved is True
        assert "Resolved with phone +919999988888" in unprocessed.review_notes

        # Created lead verification
        lead = Lead.objects.get(meta_lead_id="resolve_me_001")
        assert lead.customer.phone == "+919999988888"
        assert lead.customer.name == "Sunil Sharma"

        # Log linked to lead
        log.refresh_from_db()
        assert log.lead == lead

    def test_sweep_stuck_meta_webhooks(self):
        """Stuck webhooks in 'received' status older than 5 minutes are re-queued."""
        now = timezone.now()
        # Fresh log (under 5 mins) -> should NOT be re-queued
        MetaWebhookLog.objects.create(
            meta_lead_id="fresh_log_01",
            status=WebhookLogStatus.RECEIVED,
        )

        # Stuck log (10 mins old, attempts < 3) -> should be re-queued
        stuck_log = MetaWebhookLog.objects.create(
            meta_lead_id="stuck_log_02",
            status=WebhookLogStatus.RECEIVED,
            attempts=1,
            payload={
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Stuck Lead"]},
                        {"name": "phone", "values": ["+919333344444"]},
                    ]
                }
            },
        )
        MetaWebhookLog.objects.filter(id=stuck_log.id).update(
            created_at=now - timedelta(minutes=10)
        )

        # Exhausted log (10 mins old, attempts >= 3) -> should be marked ERROR
        exhausted_log = MetaWebhookLog.objects.create(
            meta_lead_id="exhausted_log_03",
            status=WebhookLogStatus.RECEIVED,
            attempts=3,
        )
        MetaWebhookLog.objects.filter(id=exhausted_log.id).update(
            created_at=now - timedelta(minutes=10)
        )

        result = sweep_stuck_meta_webhooks()
        assert result["requeued"] == 1
        assert result["exhausted"] == 1

        stuck_log.refresh_from_db()
        assert stuck_log.status == WebhookLogStatus.PROCESSED

        exhausted_log.refresh_from_db()
        assert exhausted_log.status == WebhookLogStatus.ERROR

    def test_sweep_stops_after_attempt_limit(self):
        """Sweep task strictly ignores logs that have already reached or exceeded MAX_WEBHOOK_ATTEMPTS."""
        now = timezone.now()
        # Row already at attempt limit and marked ERROR
        error_log = MetaWebhookLog.objects.create(
            meta_lead_id="already_error_lead",
            status=WebhookLogStatus.ERROR,
            attempts=3,
        )
        MetaWebhookLog.objects.filter(id=error_log.id).update(
            created_at=now - timedelta(minutes=15)
        )

        # Run sweep
        result = sweep_stuck_meta_webhooks()
        assert result["requeued"] == 0
        assert result["exhausted"] == 0

        # Row remains untouched with attempts unchanged
        error_log.refresh_from_db()
        assert error_log.attempts == 3
        assert error_log.status == WebhookLogStatus.ERROR

    def test_cleanup_old_meta_webhook_logs(self):
        """Retention task deletes webhook logs older than 90 days."""
        now = timezone.now()
        # Old log (100 days old)
        old_log = MetaWebhookLog.objects.create(meta_lead_id="old_log")
        MetaWebhookLog.objects.filter(id=old_log.id).update(created_at=now - timedelta(days=100))

        # Recent log (10 days old)
        recent_log = MetaWebhookLog.objects.create(meta_lead_id="recent_log")
        MetaWebhookLog.objects.filter(id=recent_log.id).update(created_at=now - timedelta(days=10))

        cleanup_old_meta_webhook_logs()

        assert not MetaWebhookLog.objects.filter(meta_lead_id="old_log").exists()
        assert MetaWebhookLog.objects.filter(meta_lead_id="recent_log").exists()

    def test_manager_only_webhook_log_access_and_retry(self, api_client, meta_users):
        """Staff receives 403 when accessing webhook logs; Manager can view and retry."""
        log = MetaWebhookLog.objects.create(
            meta_lead_id="audit_log_01",
            status=WebhookLogStatus.ERROR,
            error_message="Temporary failure",
            payload={
                "lead_data": {
                    "field_data": [
                        {"name": "name", "values": ["Retry Lead"]},
                        {"name": "phone", "values": ["+919444455555"]},
                    ]
                }
            },
        )

        # Staff forbidden
        api_client.force_authenticate(user=meta_users["staff1"])
        resp_staff = api_client.get("/api/integrations/meta/logs/")
        assert resp_staff.status_code == status.HTTP_403_FORBIDDEN

        # Manager authorized
        api_client.force_authenticate(user=meta_users["manager"])
        resp_mgr = api_client.get("/api/integrations/meta/logs/")
        assert resp_mgr.status_code == status.HTTP_200_OK
        assert len(resp_mgr.data) >= 1

        # Manager retry action
        retry_resp = api_client.post(f"/api/integrations/meta/logs/{log.id}/retry/")
        assert retry_resp.status_code == status.HTTP_200_OK
        log.refresh_from_db()
        assert log.status == WebhookLogStatus.PROCESSED

    def test_create_lead_with_created_by_none(self):
        """LeadService.create_lead succeeds without errors when user=None."""
        result = LeadService.create_lead(
            customer_data={
                "name": "System Lead Customer",
                "phone": "+919555566666",
            },
            lead_data={
                "source": LeadSource.META_LEAD_ADS,
                "title": "System Lead",
            },
            user=None,
        )
        lead = result["lead"]
        assert lead is not None
        assert lead.created_by is None
        assert lead.customer.created_by is None
