import hashlib
import hmac
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import NotificationType
from apps.activities.services import NotificationService
from apps.integrations_meta.models import MetaWebhookLog, WebhookLogStatus
from apps.leads.models import (
    Customer,
    Lead,
    LeadAssignment,
    LeadSource,
    ProductCategory,
    UnprocessedMetaLead,
)
from apps.leads.services import CustomerService, LeadService

UTC = ZoneInfo("UTC")
MAX_WEBHOOK_ATTEMPTS = 3


class MetaGraphPermanentError(Exception):
    """Non-retryable 4xx error from Meta Graph API."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Meta Graph API HTTP {status_code}: {message}")


class MetaSecurityService:
    """Security verification and signature handling for Meta webhooks."""

    @staticmethod
    def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
        """
        Verify X-Hub-Signature-256 header against raw request body using HMAC-SHA256.
        Fails closed if META_APP_SECRET is unset or empty.
        """
        secret = getattr(settings, "META_APP_SECRET", "")
        if not secret or not signature_header:
            return False

        if not signature_header.startswith("sha256="):
            return False

        expected_sig = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        provided_sig = signature_header.split("sha256=", 1)[1].strip()
        return hmac.compare_digest(expected_sig, provided_sig)

    @staticmethod
    def verify_hub_token(verify_token: str | None) -> bool:
        """
        Verify hub.verify_token for webhook subscription verification.
        Uses hmac.compare_digest for constant-time comparison.
        """
        configured_token = getattr(settings, "META_VERIFY_TOKEN", "")
        if not configured_token or not verify_token:
            return False
        return hmac.compare_digest(configured_token, verify_token)

    @staticmethod
    def get_client_ip(request) -> str:
        """Extract client IP, deliberately handling X-Forwarded-For."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


class MetaFieldMapper:
    """Tolerant parsing and field extraction for Meta Lead Ad form variations."""

    @staticmethod
    def extract_lead_fields(lead_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Extract normalized lead and customer fields from Meta payload or Graph API response.
        Strips 'p:' phone prefix, extracts name/email, maps product interest and budget.
        """
        field_data = lead_dict.get("field_data", [])
        fields_by_name: dict[str, str] = {}

        if isinstance(field_data, list):
            for item in field_data:
                name = str(item.get("name", "")).strip().lower()
                values = item.get("values", [])
                val = str(values[0]).strip() if values else ""
                if name:
                    fields_by_name[name] = val
        elif isinstance(field_data, dict):
            for k, v in field_data.items():
                fields_by_name[str(k).strip().lower()] = str(v).strip()

        # Phone extraction
        phone = ""
        for key in ["phone_number", "phone", "mobile_number", "mobile", "contact_number"]:
            if key in fields_by_name and fields_by_name[key]:
                phone = fields_by_name[key]
                break
        if not phone:
            for k, v in fields_by_name.items():
                if ("phone" in k or "mobile" in k or "contact" in k) and v:
                    phone = v
                    break

        # Strip "p:" prefix if present
        if phone.lower().startswith("p:"):
            phone = phone[2:].strip()

        # Name extraction
        name = ""
        for key in ["full_name", "name", "your_name"]:
            if key in fields_by_name and fields_by_name[key]:
                name = fields_by_name[key]
                break
        if not name:
            first = fields_by_name.get("first_name", "")
            last = fields_by_name.get("last_name", "")
            name = f"{first} {last}".strip()

        # Email extraction
        email = ""
        for key in ["email", "email_address", "contact_email"]:
            if key in fields_by_name and fields_by_name[key]:
                email = fields_by_name[key]
                break

        # Product interest mapping
        product_category = ""
        product_text = ""
        for k, v in fields_by_name.items():
            if any(term in k for term in ["product", "looking_for", "interested", "category"]):
                product_text = v.lower()
                break

        if product_text:
            if "laptop" in product_text:
                product_category = ProductCategory.LAPTOP
            elif any(t in product_text for t in ["gaming", "rtx"]):
                product_category = ProductCategory.GAMING_PC
            elif any(t in product_text for t in ["desktop", "build", "custom pc", "pc build"]):
                product_category = ProductCategory.DESKTOP_BUILD
            elif any(
                t in product_text for t in ["monitor", "keyboard", "mouse", "peripheral", "display"]
            ):
                product_category = ProductCategory.PERIPHERALS
            elif any(
                t in product_text for t in ["component", "upgrade", "ram", "gpu", "ssd", "cpu"]
            ):
                product_category = ProductCategory.COMPONENTS
            elif any(t in product_text for t in ["repair", "service", "fix"]):
                product_category = ProductCategory.REPAIR_SERVICE
            else:
                product_category = ProductCategory.OTHER

        # Budget extraction
        budget_min = None
        budget_max = None
        budget_text = ""
        for k, v in fields_by_name.items():
            if "budget" in k or "price" in k:
                budget_text = v
                break

        if budget_text:
            numbers = re.findall(r"\d[\d,]*", budget_text)
            parsed_numbers = []
            for num_str in numbers:
                try:
                    parsed_numbers.append(float(num_str.replace(",", "")))
                except ValueError:
                    pass
            if len(parsed_numbers) == 1:
                budget_max = parsed_numbers[0]
            elif len(parsed_numbers) >= 2:
                budget_min = min(parsed_numbers[0], parsed_numbers[1])
                budget_max = max(parsed_numbers[0], parsed_numbers[1])

        # Preserve created_time
        meta_created_time = lead_dict.get("created_time")

        return {
            "name": name,
            "phone": phone,
            "email": email,
            "product_category": product_category,
            "budget_min": budget_min,
            "budget_max": budget_max,
            "campaign_name": lead_dict.get("campaign_name", ""),
            "ad_id": str(lead_dict.get("ad_id", "")),
            "form_id": str(lead_dict.get("form_id", "")),
            "meta_created_time": meta_created_time,
            "raw_meta_data": lead_dict,
        }


class MetaAssignmentService:
    """Lead assignment logic for Meta leads: customer-affinity routing and round-robin."""

    @staticmethod
    def determine_lead_assignee(customer: Customer) -> User | None:
        """
        Determine assignee for a new Meta lead:
        1. If the customer already has an active, open lead with an assignee,
           assign to that existing assignee.
        2. Otherwise, round-robin among active staff with receives_meta_leads=True.
           In transaction.atomic(), lock eligible staff rows with select_for_update(of=('self',)),
           pick the oldest last_meta_lead_assigned_at (nulls first), and update it in the same transaction.
        3. If no staff are flagged, return None (unassigned for managers).
        """
        # Rule 1: Customer affinity routing (open lead with assignee)
        open_lead = (
            Lead.objects.filter(
                customer=customer,
                is_active=True,
                stage__is_won=False,
                stage__is_lost=False,
                assigned_to__isnull=False,
            )
            .select_related("assigned_to")
            .order_by("-created_at")
            .first()
        )
        if open_lead and open_lead.assigned_to and open_lead.assigned_to.is_active:
            return open_lead.assigned_to

        # Rule 2: Round-robin with row locking (skip_locked prevents concurrent collision)
        eligible_staff = (
            User.objects.filter(
                role=User.Role.STAFF,
                is_active=True,
                receives_meta_leads=True,
            )
            .select_for_update(of=("self",), skip_locked=True)
            .order_by(models.F("last_meta_lead_assigned_at").asc(nulls_first=True), "id")
        )
        selected_staff = eligible_staff.first()
        if not selected_staff:
            # Fallback if all flagged staff were momentarily locked by concurrent transactions
            fallback_qs = (
                User.objects.filter(
                    role=User.Role.STAFF,
                    is_active=True,
                    receives_meta_leads=True,
                )
                .select_for_update(of=("self",))
                .order_by(models.F("last_meta_lead_assigned_at").asc(nulls_first=True), "id")
            )
            selected_staff = fallback_qs.first()

        if selected_staff:
            selected_staff.last_meta_lead_assigned_at = timezone.now()
            selected_staff.save(update_fields=["last_meta_lead_assigned_at"])
            return selected_staff

        return None


class MetaLeadService:
    """Business logic for Meta webhook ingestion, Graph API fetch, and processing."""

    @staticmethod
    def fetch_lead_from_graph_api(meta_lead_id: str) -> dict[str, Any]:
        """
        Fetch lead details from Meta Graph API using the configured Page Access Token.
        Never logs or exposes tokens in errors. Retries on timeouts, connection errors, 429, 5xx.
        Raises MetaGraphPermanentError for non-retryable 4xx errors.
        """
        page_token = getattr(settings, "META_PAGE_ACCESS_TOKEN", "")
        graph_version = getattr(settings, "META_GRAPH_VERSION", "v22.0")
        url = f"https://graph.facebook.com/{graph_version}/{meta_lead_id}"

        headers = {
            "Authorization": f"Bearer {page_token}",
            "User-Agent": "ShopCRM-MetaIntegration/1.0",
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=(5.0, 15.0),
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            # Re-raise for Celery retry
            raise exc

        if response.status_code == 429 or response.status_code >= 500:
            # Transient server/rate limit error: trigger Celery retry
            response.raise_for_status()

        if 400 <= response.status_code < 500:
            # Permanent client error (e.g. invalid token, expired token, missing permissions)
            sanitized_msg = (
                f"Meta API error (HTTP {response.status_code}) for leadgen_id {meta_lead_id}"
            )
            try:
                err_data = response.json().get("error", {})
                err_type = err_data.get("type", "OAuthException")
                err_code = err_data.get("code", "")
                sanitized_msg = f"{err_type} (code {err_code}): {err_data.get('message', '')}"
            except Exception:
                pass
            raise MetaGraphPermanentError(response.status_code, sanitized_msg)

        return response.json()

    @classmethod
    @transaction.atomic
    def process_meta_webhook_log(cls, log_id: int) -> MetaWebhookLog:
        """
        Process a single MetaWebhookLog row idempotently.
        Handles leadgen fetch, phone validation, customer dedupe, assignment, and notifications.
        """
        log = MetaWebhookLog.objects.select_for_update(of=("self",)).get(pk=log_id)

        # Skip if already processed or duplicate
        if log.status in (WebhookLogStatus.PROCESSED, WebhookLogStatus.DUPLICATE):
            return log

        log.attempts += 1

        meta_lead_id = log.meta_lead_id
        payload = log.payload or {}

        # 1. Idempotency check: Does Lead or UnprocessedMetaLead already have this meta_lead_id?
        if meta_lead_id:
            existing_lead = Lead.objects.filter(meta_lead_id=meta_lead_id).first()
            if existing_lead:
                log.status = WebhookLogStatus.DUPLICATE
                log.lead = existing_lead
                log.processed_at = timezone.now()
                log.save(update_fields=["status", "lead", "processed_at", "attempts"])
                return log

            existing_unprocessed = UnprocessedMetaLead.objects.filter(
                meta_lead_id=meta_lead_id
            ).first()
            if existing_unprocessed:
                log.status = WebhookLogStatus.DUPLICATE
                log.unprocessed_lead = existing_unprocessed
                log.processed_at = timezone.now()
                log.save(update_fields=["status", "unprocessed_lead", "processed_at", "attempts"])
                return log

        # 2. Extract or fetch lead data
        # Check if full lead data is already in payload (e.g. in tests/mocks or direct ingestion)
        lead_data = payload.get("lead_data")
        if not lead_data and "field_data" in payload:
            lead_data = payload

        if not lead_data and meta_lead_id:
            try:
                lead_data = cls.fetch_lead_from_graph_api(meta_lead_id)
            except MetaGraphPermanentError as err:
                log.status = WebhookLogStatus.ERROR
                log.error_message = err.message
                log.processed_at = timezone.now()
                log.save(update_fields=["status", "error_message", "processed_at", "attempts"])
                # Notify managers about the permanent token/API failure
                cls.notify_managers_of_api_error(log)
                return log
            except Exception as exc:
                # Check if retry limit reached
                if log.attempts >= MAX_WEBHOOK_ATTEMPTS:
                    log.status = WebhookLogStatus.ERROR
                    log.error_message = f"Retries exhausted: {str(exc)}"
                    log.processed_at = timezone.now()
                    log.save(update_fields=["status", "error_message", "processed_at", "attempts"])
                    return log
                log.save(update_fields=["attempts"])
                raise exc

        if not lead_data:
            lead_data = payload

        # 3. Parse and extract fields
        parsed = MetaFieldMapper.extract_lead_fields(lead_data)
        phone = parsed.get("phone", "")
        extracted_meta_lead_id = meta_lead_id or str(lead_data.get("id") or "")
        campaign_name = parsed.get("campaign_name") or payload.get("campaign_name", "")
        ad_id = parsed.get("ad_id") or str(payload.get("ad_id", ""))
        form_id = parsed.get("form_id") or str(payload.get("form_id", ""))

        # 4. If phone is missing: store in UnprocessedMetaLead and notify managers
        if not phone or not phone.strip():
            try:
                unprocessed = UnprocessedMetaLead.objects.create(
                    meta_lead_id=extracted_meta_lead_id
                    or f"meta_nophone_{timezone.now().timestamp()}",
                    campaign_name=campaign_name,
                    ad_id=ad_id,
                    form_id=form_id,
                    raw_payload=lead_data,
                    review_notes="Meta lead ingested without a phone number; awaiting manager review.",
                )
            except IntegrityError:
                # Concurrent delivery created the unprocessed lead
                existing_unprocessed = UnprocessedMetaLead.objects.filter(
                    meta_lead_id=extracted_meta_lead_id
                ).first()
                log.status = WebhookLogStatus.DUPLICATE
                log.unprocessed_lead = existing_unprocessed
                log.processed_at = timezone.now()
                log.save(update_fields=["status", "unprocessed_lead", "processed_at", "attempts"])
                return log

            log.status = WebhookLogStatus.PROCESSED
            log.unprocessed_lead = unprocessed
            log.processed_at = timezone.now()
            log.save(update_fields=["status", "unprocessed_lead", "processed_at", "attempts"])

            # Notify managers
            cls.notify_managers_of_unprocessed_lead(unprocessed)
            return log

        # 5. If phone is present: create Customer + Lead with assignment routing
        customer_name = parsed.get("name") or "Meta Ad Inquiry"
        try:
            customer, _ = CustomerService.get_or_create_customer(
                phone=phone,
                name=customer_name,
                email=parsed.get("email", ""),
                created_by=None,
            )

            # Determine assignee (customer affinity or round-robin)
            assignee = MetaAssignmentService.determine_lead_assignee(customer)

            raw_meta = dict(parsed.get("raw_meta_data", {}))
            if parsed.get("meta_created_time"):
                raw_meta["created_time"] = parsed["meta_created_time"]

            # Create lead using LeadService
            result = LeadService.create_lead(
                customer_data={
                    "phone": phone,
                    "name": customer_name,
                    "email": parsed.get("email", ""),
                },
                lead_data={
                    "source": LeadSource.META_LEAD_ADS,
                    "meta_lead_id": extracted_meta_lead_id,
                    "campaign_name": campaign_name,
                    "ad_id": ad_id,
                    "form_id": form_id,
                    "product_category": parsed.get("product_category", ""),
                    "budget_min": parsed.get("budget_min"),
                    "budget_max": parsed.get("budget_max"),
                    "raw_meta_data": raw_meta,
                    "assigned_to": assignee,
                },
                user=None,  # System/webhook creation
            )
            lead = result.get("lead")

            # Update assigned_to and lead assignment if routing selected an assignee
            if lead and assignee and lead.assigned_to != assignee:
                lead.assigned_to = assignee
                lead.save(update_fields=["assigned_to", "updated_at"])
                LeadAssignment.objects.create(
                    lead=lead,
                    assigned_by=None,
                    from_user=None,
                    to_user=assignee,
                    reason="Auto-assigned via Meta Lead Ads routing",
                )

            # Send Notification to assignee
            if lead and assignee:
                NotificationService.create_notification(
                    user=assignee,
                    notification_type=NotificationType.NEW_LEAD,
                    dedupe_key=f"new_lead:{lead.id}:{assignee.id}",
                    title=f"New Lead: {customer.name}",
                    message=f"New lead from Meta Lead Ads ({lead.campaign_name or 'Campaign'}) assigned to you for {customer.name} ({customer.phone}).",
                    lead=lead,
                )

            log.status = WebhookLogStatus.PROCESSED
            log.lead = lead
            log.processed_at = timezone.now()
            log.save(update_fields=["status", "lead", "processed_at", "attempts"])
            return log

        except IntegrityError:
            # Concurrent delivery duplicate
            existing_lead = Lead.objects.filter(meta_lead_id=extracted_meta_lead_id).first()
            log.status = WebhookLogStatus.DUPLICATE
            log.lead = existing_lead
            log.processed_at = timezone.now()
            log.save(update_fields=["status", "lead", "processed_at", "attempts"])
            return log

    @staticmethod
    def notify_managers_of_unprocessed_lead(unprocessed: UnprocessedMetaLead):
        """Notify all active managers and admins when a lead lands in UnprocessedMetaLead."""
        managers = User.objects.filter(
            role__in=[User.Role.MANAGER, User.Role.ADMIN],
            is_active=True,
        )
        for mgr in managers:
            NotificationService.create_notification(
                user=mgr,
                notification_type=NotificationType.UNPROCESSED_META_LEAD,
                dedupe_key=f"unprocessed_meta:{unprocessed.id}:{mgr.id}",
                title="Meta Lead Missing Phone Number",
                message=f"Meta Lead #{unprocessed.meta_lead_id} requires review: missing valid phone number.",
            )

    @staticmethod
    def notify_managers_of_api_error(log: MetaWebhookLog):
        """Notify managers when Meta Graph API returns a permanent 4xx error."""
        managers = User.objects.filter(
            role__in=[User.Role.MANAGER, User.Role.ADMIN],
            is_active=True,
        )
        for mgr in managers:
            NotificationService.create_notification(
                user=mgr,
                notification_type=NotificationType.META_API_ERROR,
                dedupe_key=f"meta_api_error:{log.id}:{mgr.id}",
                title="Meta Graph API Error",
                message=f"Meta Graph API error for leadgen #{log.meta_lead_id}: {log.error_message}. Please check Page Access Token and permissions.",
            )

    @classmethod
    @transaction.atomic
    def resolve_unprocessed_meta_lead(
        cls,
        *,
        unprocessed_id: int,
        phone: str,
        user,
        name: str = "",
        email: str = "",
        notes: str = "",
    ) -> Lead:
        """
        Manager/admin service to resolve an UnprocessedMetaLead by entering a phone number.
        Runs through customer creation, lead creation, and assignment routing.
        """
        if not getattr(user, "can_view_all_leads", False):
            raise PermissionDenied("Only managers or admins can resolve unprocessed Meta leads.")

        unprocessed = UnprocessedMetaLead.objects.select_for_update().get(pk=unprocessed_id)
        if unprocessed.is_resolved:
            raise ValidationError("This unprocessed lead has already been resolved.")

        if not phone or not phone.strip():
            raise ValidationError(
                {"phone": "A valid phone number is required to resolve this lead."}
            )

        raw_payload = unprocessed.raw_payload or {}
        parsed = MetaFieldMapper.extract_lead_fields(raw_payload)

        customer_name = name.strip() or parsed.get("name") or "Resolved Meta Inquiry"
        customer_email = email.strip() or parsed.get("email", "")

        customer, _ = CustomerService.get_or_create_customer(
            phone=phone,
            name=customer_name,
            email=customer_email,
            created_by=user,
        )

        assignee = MetaAssignmentService.determine_lead_assignee(customer)

        raw_meta = dict(raw_payload)
        if parsed.get("meta_created_time"):
            raw_meta["created_time"] = parsed["meta_created_time"]

        result = LeadService.create_lead(
            customer_data={
                "phone": phone,
                "name": customer_name,
                "email": customer_email,
            },
            lead_data={
                "source": LeadSource.META_LEAD_ADS,
                "meta_lead_id": unprocessed.meta_lead_id,
                "campaign_name": unprocessed.campaign_name,
                "ad_id": unprocessed.ad_id,
                "form_id": unprocessed.form_id,
                "product_category": parsed.get("product_category", ""),
                "budget_min": parsed.get("budget_min"),
                "budget_max": parsed.get("budget_max"),
                "raw_meta_data": raw_meta,
                "assigned_to": assignee,
                "notes": notes.strip(),
            },
            user=user,
        )
        lead = result["lead"]

        if lead and assignee and lead.assigned_to != assignee:
            lead.assigned_to = assignee
            lead.save(update_fields=["assigned_to", "updated_at"])
            LeadAssignment.objects.create(
                lead=lead,
                assigned_by=user,
                from_user=None,
                to_user=assignee,
                reason="Auto-assigned via Meta Lead Ads routing upon resolution",
            )

        if lead and assignee:
            NotificationService.create_notification(
                user=assignee,
                notification_type=NotificationType.NEW_LEAD,
                dedupe_key=f"new_lead:{lead.id}:{assignee.id}",
                title=f"New Lead: {customer.name}",
                message=f"Meta Lead #{unprocessed.meta_lead_id} was resolved and assigned to you.",
                lead=lead,
            )

        unprocessed.is_resolved = True
        unprocessed.review_notes = (
            f"{unprocessed.review_notes}\nResolved with phone {phone} by {user.username}."
        ).strip()
        unprocessed.save(update_fields=["is_resolved", "review_notes"])

        # Update any related MetaWebhookLog
        MetaWebhookLog.objects.filter(meta_lead_id=unprocessed.meta_lead_id).update(
            lead=lead,
            status=WebhookLogStatus.PROCESSED,
            processed_at=timezone.now(),
        )

        return lead
