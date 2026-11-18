import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsManagerOrAdmin
from apps.activities.serializers import ActivitySerializer, FollowUpSerializer
from apps.leads.models import Customer, Lead, Stage, UnprocessedMetaLead
from apps.leads.permissions import (
    IsAssignedStaffOrManagerOrAdmin,
    IsManagerOrAdminForCustomerPhone,
)
from apps.leads.serializers import (
    ChangeStageSerializer,
    CheckPhoneRequestSerializer,
    CustomerSerializer,
    LeadAssignmentSerializer,
    LeadCreateSerializer,
    LeadSerializer,
    ReassignLeadSerializer,
    StageHistorySerializer,
    StageSerializer,
    UnprocessedMetaLeadSerializer,
    UpdateDealValueSerializer,
)
from apps.leads.services import (
    CustomerService,
    LeadAssignmentService,
    LeadStageService,
)
from apps.leads.throttling import (
    CheckPhoneIPThrottle,
    CheckPhoneUserDailyThrottle,
    CheckPhoneUserMinuteThrottle,
)


class StageViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve pipeline stages in order."""

    queryset = Stage.objects.all().order_by("order")
    serializer_class = StageSerializer
    permission_classes = [IsAuthenticated]


class CustomerViewSet(viewsets.ModelViewSet):
    """
    Customer master viewset.
    Staff see only customers associated with their assigned/created leads.
    Managers/Admins see all customers.
    """

    serializer_class = CustomerSerializer
    permission_classes = [
        IsAuthenticated,
        IsAssignedStaffOrManagerOrAdmin,
        IsManagerOrAdminForCustomerPhone,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "phone", "email", "company_name"]
    ordering_fields = ["id", "name", "created_at", "total_spend"]
    ordering = ["-id"]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, "can_view_all_leads", False):
            qs = Customer.objects.all()
        else:
            qs = Customer.objects.filter(
                Q(leads__assigned_to=user) | Q(leads__created_by=user)
            ).distinct()

        # Phone search normalization: if search term has digits, match against normalized phone
        search_term = self.request.query_params.get("search", "").strip()
        if search_term:
            clean_digits = re.sub(r"\D", "", search_term)
            if len(clean_digits) >= 4:
                qs = qs.filter(
                    Q(phone__icontains=clean_digits)
                    | Q(name__icontains=search_term)
                    | Q(email__icontains=search_term)
                    | Q(company_name__icontains=search_term)
                )

        return qs.order_by("-id")

    @action(detail=True, methods=["post"], permission_classes=[IsManagerOrAdmin])
    def merge(self, request, pk=None):
        """Merge this customer into another target customer."""
        source_customer = self.get_object()
        target_customer_id = request.data.get("target_customer_id")
        if not target_customer_id:
            raise ValidationError({"target_customer_id": "Target customer ID is required."})

        target_customer = Customer.objects.filter(pk=target_customer_id).first()
        if not target_customer:
            raise ValidationError({"target_customer_id": "Target customer not found."})

        try:
            merged = CustomerService.merge_customers(source_customer, target_customer, request.user)
            return Response(CustomerSerializer(merged, context={"request": request}).data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))


class LeadViewSet(viewsets.ModelViewSet):
    """
    Lead lifecycle and pipeline management.
    Staff see and edit only their assigned leads.
    Managers/Admins see all leads (including unassigned and Meta leads).
    """

    permission_classes = [IsAuthenticated, IsAssignedStaffOrManagerOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["customer__name", "customer__phone", "title", "notes"]
    ordering_fields = ["id", "created_at", "last_activity_at", "deal_value", "updated_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return LeadCreateSerializer
        return LeadSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Lead.objects.select_related("customer", "stage", "assigned_to", "created_by")

        # Staff scoping: staff are ALWAYS forced to their assigned active leads only
        if getattr(user, "can_view_all_leads", False):
            assigned_to_param = self.request.query_params.get("assigned_to")
            if assigned_to_param:
                if assigned_to_param == "unassigned":
                    qs = qs.filter(assigned_to__isnull=True)
                elif assigned_to_param.isdigit():
                    qs = qs.filter(assigned_to_id=int(assigned_to_param))

            is_active_param = self.request.query_params.get("is_active")
            if is_active_param is not None:
                qs = qs.filter(is_active=is_active_param.lower() in ("true", "1"))
            else:
                qs = qs.filter(is_active=True)
        else:
            # Staff are strictly forced to their own active leads even if assigned_to is passed
            qs = qs.filter(assigned_to=user, is_active=True)

        # Stage filter
        stage_param = self.request.query_params.get("stage")
        if stage_param:
            if stage_param.isdigit():
                qs = qs.filter(stage_id=int(stage_param))
            else:
                qs = qs.filter(stage__slug=stage_param)

        # Source filter
        source_param = self.request.query_params.get("source")
        if source_param:
            qs = qs.filter(source=source_param)

        # Product category filter
        cat_param = self.request.query_params.get("product_category")
        if cat_param:
            qs = qs.filter(product_category=cat_param)

        # Phone search normalization
        search_term = self.request.query_params.get("search", "").strip()
        if search_term:
            clean_digits = re.sub(r"\D", "", search_term)
            if len(clean_digits) >= 4:
                qs = qs.filter(
                    Q(customer__phone__icontains=clean_digits)
                    | Q(customer__name__icontains=search_term)
                    | Q(title__icontains=search_term)
                    | Q(notes__icontains=search_term)
                )

        return qs.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            result = serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

        if result.get("status") == "stored_for_review":
            return Response(
                {
                    "status": "stored_for_review",
                    "message": "Meta lead stored for manager review because phone number was missing.",
                    "unprocessed_meta_lead_id": result["unprocessed_meta_lead"].id,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        lead = result["lead"]
        lead_data = LeadSerializer(lead, context={"request": request}).data
        response_data = {
            "lead": lead_data,
            "existing_customer": result["existing_customer"],
            "open_leads_warning": result["open_leads_warning"],
        }
        return Response(response_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def change_stage(self, request, pk=None):
        """Atomically advance or transition lead stage."""
        lead = self.get_object()
        serializer = ChangeStageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        to_stage = None
        if data.get("to_stage_id"):
            to_stage = Stage.objects.filter(pk=data["to_stage_id"]).first()
        elif data.get("to_stage_slug"):
            to_stage = Stage.objects.filter(slug=data["to_stage_slug"]).first()

        if not to_stage:
            raise ValidationError({"stage": "Target stage not found."})

        try:
            updated_lead = LeadStageService.change_stage(
                lead_id=lead.id,
                to_stage=to_stage,
                user=request.user,
                deal_value=data.get("deal_value"),
                lost_reason_category=data.get("lost_reason_category", ""),
                lost_reason_notes=data.get("lost_reason_notes", ""),
                notes=data.get("notes", ""),
            )
            return Response(LeadSerializer(updated_lead, context={"request": request}).data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    @action(detail=True, methods=["post"], permission_classes=[IsManagerOrAdmin])
    def reassign(self, request, pk=None):
        """Reassign lead to another user and transfer pending follow-ups (Manager/Admin only)."""
        lead = self.get_object()
        serializer = ReassignLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        to_user_id = serializer.validated_data["to_user_id"]
        to_user = User.objects.filter(pk=to_user_id, is_active=True).first()
        if not to_user:
            raise ValidationError({"to_user_id": "Target assignee user not found or inactive."})

        try:
            updated_lead = LeadAssignmentService.reassign(
                lead_id=lead.id,
                to_user=to_user,
                assigned_by=request.user,
                reason=serializer.validated_data.get("reason", ""),
            )
            return Response(LeadSerializer(updated_lead, context={"request": request}).data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    @action(detail=True, methods=["post"], permission_classes=[IsManagerOrAdmin])
    def update_deal_value(self, request, pk=None):
        """Update deal_value on a Won lead (Manager/Admin only)."""
        lead = self.get_object()
        serializer = UpdateDealValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated_lead = LeadStageService.update_deal_value(
                lead_id=lead.id,
                new_deal_value=serializer.validated_data["deal_value"],
                user=request.user,
                reason=serializer.validated_data.get("reason", ""),
            )
            return Response(LeadSerializer(updated_lead, context={"request": request}).data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    @action(detail=True, methods=["get"])
    def stage_history(self, request, pk=None):
        """View stage transition audit history for this lead."""
        lead = self.get_object()
        history = lead.stage_history.select_related("from_stage", "to_stage", "user").order_by(
            "-timestamp"
        )
        return Response(StageHistorySerializer(history, many=True).data)

    @action(detail=True, methods=["get"])
    def assignments(self, request, pk=None):
        """View assignment and reassignment audit history for this lead."""
        lead = self.get_object()
        assignments = lead.assignments.select_related(
            "assigned_by", "from_user", "to_user"
        ).order_by("-timestamp")
        return Response(LeadAssignmentSerializer(assignments, many=True).data)

    @action(detail=True, methods=["get", "post"])
    def activities(self, request, pk=None):
        """List or log activities for this lead."""
        lead = self.get_object()
        if request.method == "GET":
            acts = lead.activities.select_related("user").order_by("-occurred_at")
            return Response(ActivitySerializer(acts, many=True).data)

        # POST: log new activity
        serializer = ActivitySerializer(
            data={**request.data, "lead": lead.id}, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            activity = serializer.save()
            return Response(ActivitySerializer(activity).data, status=status.HTTP_201_CREATED)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    @action(detail=True, methods=["get", "post"])
    def follow_ups(self, request, pk=None):
        """List or schedule follow-up reminders for this lead."""
        lead = self.get_object()
        if request.method == "GET":
            fups = lead.follow_ups.select_related("assigned_to", "completed_by").order_by(
                "scheduled_at"
            )
            return Response(FollowUpSerializer(fups, many=True).data)

        # POST: schedule follow-up
        serializer = FollowUpSerializer(
            data={**request.data, "lead": lead.id}, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            follow_up = serializer.save()
            return Response(FollowUpSerializer(follow_up).data, status=status.HTTP_201_CREATED)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    @action(
        detail=False,
        methods=["post"],
        url_path="check-phone",
        permission_classes=[IsAuthenticated],
        throttle_classes=[
            CheckPhoneUserMinuteThrottle,
            CheckPhoneUserDailyThrottle,
            CheckPhoneIPThrottle,
        ],
    )
    @extend_schema(
        request=CheckPhoneRequestSerializer,
        summary="Check customer phone number for duplicate records and open leads",
    )
    def check_phone(self, request):
        """
        Check if a phone number belongs to an existing customer and return open leads.
        Staff get limited information only (customer id/name, open lead stages & assignees).
        Managers/admins get full customer details including spend and contact data.
        Throttled per user (20/min, 200/day) and per IP (30/min).
        """
        phone = request.data.get("phone", "")
        if not phone or not str(phone).strip():
            raise ValidationError({"phone": "Phone number is required."})

        try:
            cleaned_phone = CustomerService.clean_phone(phone)
        except DjangoValidationError as exc:
            raise ValidationError(
                {"phone": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}
            )

        customer = Customer.objects.filter(phone=cleaned_phone).first()
        if not customer:
            return Response({"exists": False, "customer": None, "open_leads": []})

        open_leads = (
            Lead.objects.filter(
                customer=customer,
                is_active=True,
                stage__is_won=False,
                stage__is_lost=False,
            )
            .select_related("stage", "assigned_to")
            .order_by("-created_at")
        )

        if getattr(request.user, "can_view_all_leads", False):
            return Response(
                {
                    "exists": True,
                    "customer": {
                        "id": customer.id,
                        "name": customer.name,
                        "phone": customer.phone,
                        "email": customer.email,
                        "total_spend": str(customer.total_spend),
                        "created_at": customer.created_at.isoformat(),
                    },
                    "open_leads": [
                        {
                            "id": lead.id,
                            "title": lead.title,
                            "stage_id": lead.stage_id,
                            "stage_name": lead.stage.name,
                            "assigned_to_id": lead.assigned_to_id,
                            "assigned_to_name": (
                                lead.assigned_to.username if lead.assigned_to else "Unassigned"
                            ),
                            "is_assigned_to_me": lead.assigned_to_id == request.user.id,
                            "deal_value": str(lead.deal_value) if lead.deal_value else None,
                            "created_at": lead.created_at.isoformat(),
                        }
                        for lead in open_leads
                    ],
                }
            )

        return Response(
            {
                "exists": True,
                "customer": {
                    "id": customer.id,
                    "name": customer.name,
                },
                "open_leads": [
                    {
                        "id": lead.id,
                        "stage_name": lead.stage.name,
                        "assigned_to_name": (
                            lead.assigned_to.username if lead.assigned_to else "Unassigned"
                        ),
                        "is_assigned_to_me": lead.assigned_to_id == request.user.id,
                    }
                    for lead in open_leads
                ],
            }
        )


class UnprocessedMetaLeadViewSet(viewsets.ModelViewSet):
    """View and resolve Meta lead payloads missing phone numbers (Manager/Admin only)."""

    queryset = UnprocessedMetaLead.objects.all().order_by("-created_at")
    serializer_class = UnprocessedMetaLeadSerializer
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        """Manager resolves an unprocessed lead by supplying a valid phone number."""
        unprocessed = self.get_object()
        phone = request.data.get("phone", "")
        if not phone:
            raise ValidationError({"phone": "Phone number is required to resolve this lead."})

        from apps.integrations_meta.services import MetaLeadService

        try:
            lead = MetaLeadService.resolve_unprocessed_meta_lead(
                unprocessed_id=unprocessed.id,
                phone=phone,
                user=request.user,
                name=request.data.get("name", ""),
                email=request.data.get("email", ""),
                notes=request.data.get("notes", ""),
            )
            return Response(LeadSerializer(lead).data, status=status.HTTP_200_OK)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))
