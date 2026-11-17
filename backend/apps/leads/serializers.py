from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User
from apps.leads.models import (
    Customer,
    CustomerType,
    Lead,
    LeadAssignment,
    LeadSource,
    LostReasonCategory,
    ProductCategory,
    Stage,
    StageHistory,
    UnprocessedMetaLead,
)
from apps.leads.services import (
    CustomerService,
    LeadService,
)


class StageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stage
        fields = [
            "id",
            "name",
            "slug",
            "order",
            "is_won",
            "is_lost",
            "color",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CustomerSerializer(serializers.ModelSerializer):
    total_spend = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    last_purchase_at = serializers.DateTimeField(read_only=True)
    open_leads_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "phone",
            "alt_phone",
            "email",
            "address",
            "customer_type",
            "company_name",
            "gstin",
            "notes",
            "is_active",
            "total_spend",
            "last_purchase_at",
            "open_leads_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "total_spend",
            "last_purchase_at",
            "open_leads_count",
        ]

    def update(self, instance, validated_data):
        user = self.context["request"].user
        try:
            return CustomerService.update_customer(instance, user, **validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            )


class StageHistorySerializer(serializers.ModelSerializer):
    from_stage_name = serializers.CharField(source="from_stage.name", read_only=True)
    to_stage_name = serializers.CharField(source="to_stage.name", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = StageHistory
        fields = [
            "id",
            "lead",
            "from_stage",
            "from_stage_name",
            "to_stage",
            "to_stage_name",
            "user",
            "user_name",
            "deal_value",
            "lost_reason_category",
            "lost_reason_notes",
            "notes",
            "timestamp",
        ]
        read_only_fields = fields


class LeadAssignmentSerializer(serializers.ModelSerializer):
    assigned_by_name = serializers.CharField(source="assigned_by.username", read_only=True)
    from_user_name = serializers.CharField(source="from_user.username", read_only=True)
    to_user_name = serializers.CharField(source="to_user.username", read_only=True)

    class Meta:
        model = LeadAssignment
        fields = [
            "id",
            "lead",
            "assigned_by",
            "assigned_by_name",
            "from_user",
            "from_user_name",
            "to_user",
            "to_user_name",
            "reason",
            "timestamp",
        ]
        read_only_fields = fields


class LeadSerializer(serializers.ModelSerializer):
    """Lead representation exposing customer contact info read-only."""

    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    customer_email = serializers.CharField(source="customer.email", read_only=True)
    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_slug = serializers.CharField(source="stage.slug", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.username", read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id",
            "customer",
            "customer_name",
            "customer_phone",
            "customer_email",
            "title",
            "source",
            "campaign_name",
            "ad_id",
            "form_id",
            "meta_lead_id",
            "raw_meta_data",
            "product_category",
            "product_brand",
            "budget_min",
            "budget_max",
            "stage",
            "stage_name",
            "stage_slug",
            "deal_value",
            "lost_reason_category",
            "lost_reason_notes",
            "assigned_to",
            "assigned_to_name",
            "created_by",
            "first_contacted_at",
            "last_activity_at",
            "closed_at",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "customer",
            "stage",
            "deal_value",
            "lost_reason_category",
            "lost_reason_notes",
            "assigned_to",
            "created_by",
            "first_contacted_at",
            "last_activity_at",
            "closed_at",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Exclude raw_meta_data from staff serializers
        if request and request.user and not getattr(request.user, "can_view_all_leads", False):
            data.pop("raw_meta_data", None)
        return data

    def update(self, instance, validated_data):
        user = self.context["request"].user
        try:
            return LeadService.update_lead(instance, user, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            )


class LeadCreateSerializer(serializers.Serializer):
    """Unified creation serializer handling Customer get_or_create and duplicate warnings."""

    # Customer fields
    customer_name = serializers.CharField(max_length=150)
    customer_phone = serializers.CharField(max_length=32)
    customer_email = serializers.EmailField(required=False, allow_blank=True, default="")
    customer_alt_phone = serializers.CharField(required=False, allow_blank=True, default="")
    customer_address = serializers.CharField(required=False, allow_blank=True, default="")
    customer_type = serializers.ChoiceField(
        choices=CustomerType.choices, default=CustomerType.INDIVIDUAL
    )
    company_name = serializers.CharField(required=False, allow_blank=True, default="")
    gstin = serializers.CharField(required=False, allow_blank=True, default="")
    customer_notes = serializers.CharField(required=False, allow_blank=True, default="")

    # Lead fields
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    source = serializers.ChoiceField(choices=LeadSource.choices, default=LeadSource.WALK_IN)
    campaign_name = serializers.CharField(required=False, allow_blank=True, default="")
    ad_id = serializers.CharField(required=False, allow_blank=True, default="")
    form_id = serializers.CharField(required=False, allow_blank=True, default="")
    meta_lead_id = serializers.CharField(required=False, allow_blank=True, default="")
    raw_meta_data = serializers.JSONField(required=False, default=dict)
    product_category = serializers.ChoiceField(
        choices=ProductCategory.choices, default=ProductCategory.OTHER
    )
    product_brand = serializers.CharField(required=False, allow_blank=True, default="")
    budget_min = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    budget_max = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    assigned_to_id = serializers.IntegerField(required=False, allow_null=True)

    def create(self, validated_data):
        user = self.context["request"].user
        customer_data = {
            "name": validated_data.pop("customer_name"),
            "phone": validated_data.pop("customer_phone"),
            "email": validated_data.pop("customer_email", ""),
            "alt_phone": validated_data.pop("customer_alt_phone", ""),
            "address": validated_data.pop("customer_address", ""),
            "customer_type": validated_data.pop("customer_type", CustomerType.INDIVIDUAL),
            "company_name": validated_data.pop("company_name", ""),
            "gstin": validated_data.pop("gstin", ""),
            "notes": validated_data.pop("customer_notes", ""),
        }
        assigned_to_id = validated_data.pop("assigned_to_id", None)
        assigned_to_user = None
        if assigned_to_id and getattr(user, "can_view_all_leads", False):
            assigned_to_user = User.objects.filter(pk=assigned_to_id).first()

        lead_data = {**validated_data}
        if assigned_to_user:
            lead_data["assigned_to"] = assigned_to_user

        return LeadService.create_lead(
            customer_data=customer_data,
            lead_data=lead_data,
            user=user,
        )


class ChangeStageSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField(required=False)
    to_stage_slug = serializers.CharField(required=False)
    deal_value = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    lost_reason_category = serializers.ChoiceField(
        choices=LostReasonCategory.choices, required=False, allow_blank=True
    )
    lost_reason_notes = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("to_stage_id") and not attrs.get("to_stage_slug"):
            raise serializers.ValidationError(
                "Either to_stage_id or to_stage_slug must be provided."
            )
        return attrs


class ReassignLeadSerializer(serializers.Serializer):
    to_user_id = serializers.IntegerField(required=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class UpdateDealValueSerializer(serializers.Serializer):
    deal_value = serializers.DecimalField(max_digits=12, decimal_places=2, required=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class UnprocessedMetaLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnprocessedMetaLead
        fields = [
            "id",
            "meta_lead_id",
            "campaign_name",
            "ad_id",
            "form_id",
            "raw_payload",
            "review_notes",
            "is_resolved",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
