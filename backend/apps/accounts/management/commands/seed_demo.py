from datetime import timedelta
from decimal import Decimal

from apps.accounts.models import User
from apps.activities.models import (
    Activity,
    ActivityType,
    FollowUp,
    FollowUpStatus,
    Notification,
    NotificationType,
)
from apps.leads.models import (
    Customer,
    CustomerType,
    Lead,
    LeadSource,
    LostReasonCategory,
    ProductCategory,
    Stage,
)
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed demo data for local development and testing (DEBUG-only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            self.stderr.write(self.style.ERROR("seed_demo is strictly forbidden when DEBUG=False!"))
            return

        self.stdout.write(self.style.NOTICE("Seeding demo data..."))

        # 1. Pipeline Stages
        stages_data = [
            {"name": "New", "slug": "new", "order": 0, "is_won": False, "is_lost": False},
            {
                "name": "Contacted",
                "slug": "contacted",
                "order": 1,
                "is_won": False,
                "is_lost": False,
            },
            {"name": "Quoted", "slug": "quoted", "order": 2, "is_won": False, "is_lost": False},
            {
                "name": "Follow-up",
                "slug": "follow_up",
                "order": 3,
                "is_won": False,
                "is_lost": False,
            },
            {"name": "Won", "slug": "won", "order": 4, "is_won": True, "is_lost": False},
            {"name": "Lost", "slug": "lost", "order": 5, "is_won": False, "is_lost": True},
        ]
        stages = {}
        for s in stages_data:
            stage, _ = Stage.objects.get_or_create(
                slug=s["slug"],
                defaults={
                    "name": s["name"],
                    "order": s["order"],
                    "is_won": s["is_won"],
                    "is_lost": s["is_lost"],
                },
            )
            stages[s["slug"]] = stage

        self.stdout.write(self.style.SUCCESS("✓ Pipeline stages verified."))

        # 2. Demo Users
        users_data = [
            {
                "username": "admin",
                "email": "admin@shopcrm.local",
                "role": User.Role.ADMIN,
                "first_name": "Admin",
                "last_name": "User",
                "is_staff": True,
                "is_superuser": True,
                "receives_meta_leads": False,
            },
            {
                "username": "manager",
                "email": "manager@shopcrm.local",
                "role": User.Role.MANAGER,
                "first_name": "Sales",
                "last_name": "Manager",
                "is_staff": True,
                "is_superuser": False,
                "receives_meta_leads": False,
            },
            {
                "username": "staff1",
                "email": "staff1@shopcrm.local",
                "role": User.Role.STAFF,
                "first_name": "Vikram",
                "last_name": "Sharma",
                "is_staff": False,
                "is_superuser": False,
                "receives_meta_leads": True,
            },
            {
                "username": "staff2",
                "email": "staff2@shopcrm.local",
                "role": User.Role.STAFF,
                "first_name": "Ananya",
                "last_name": "Iyer",
                "is_staff": False,
                "is_superuser": False,
                "receives_meta_leads": True,
            },
        ]
        demo_users = {}
        for u in users_data:
            user, created = User.objects.get_or_create(
                username=u["username"],
                defaults={
                    "email": u["email"],
                    "role": u["role"],
                    "first_name": u["first_name"],
                    "last_name": u["last_name"],
                    "is_staff": u["is_staff"],
                    "is_superuser": u["is_superuser"],
                    "receives_meta_leads": u["receives_meta_leads"],
                },
            )
            user.set_password("ShopCrmDemo123!")
            user.is_active = True
            user.save()
            demo_users[u["username"]] = user

        self.stdout.write(
            self.style.SUCCESS(
                "✓ Demo users created (password: ShopCrmDemo123!):\n"
                "  - admin (Admin)\n"
                "  - manager (Manager)\n"
                "  - staff1 (Staff - receives Meta leads)\n"
                "  - staff2 (Staff - receives Meta leads)"
            )
        )

        # 3. Sample Customers
        customers_data = [
            {
                "name": "Rajesh Kumar",
                "phone": "+919876543210",
                "email": "rajesh@example.com",
                "customer_type": CustomerType.INDIVIDUAL,
            },
            {
                "name": "Priya Sharma",
                "phone": "+919876543211",
                "email": "priya@example.com",
                "customer_type": CustomerType.INDIVIDUAL,
            },
            {
                "name": "Tech Corp Solutions",
                "phone": "+919876543212",
                "email": "procurement@techcorp.local",
                "customer_type": CustomerType.BUSINESS,
                "company_name": "Tech Corp Solutions Pvt Ltd",
                "gstin": "29AABCU9603R1Z2",
            },
            {
                "name": "Sneha Reddy",
                "phone": "+919876543213",
                "email": "sneha@example.com",
                "customer_type": CustomerType.INDIVIDUAL,
            },
        ]
        customers = {}
        for c in customers_data:
            cust, _ = Customer.objects.get_or_create(
                phone=c["phone"],
                defaults={
                    "name": c["name"],
                    "email": c["email"],
                    "customer_type": c["customer_type"],
                    "company_name": c.get("company_name", ""),
                    "gstin": c.get("gstin", ""),
                    "created_by": demo_users["admin"],
                },
            )
            customers[c["phone"]] = cust

        self.stdout.write(self.style.SUCCESS("✓ Sample customers verified."))

        # 4. Sample Leads
        now = timezone.now()
        leads_data = [
            {
                "customer": customers["+919876543210"],
                "title": "Custom Gaming PC Build (RTX 4080)",
                "source": LeadSource.WALK_IN,
                "stage": stages["follow_up"],
                "assigned_to": demo_users["staff1"],
                "product_category": ProductCategory.GAMING_PC,
                "budget_min": Decimal("150000"),
                "budget_max": Decimal("200000"),
                "deal_value": Decimal("185000"),
                "notes": "Looking for white aesthetic, liquid cooling, 32GB DDR5 RAM.",
            },
            {
                "customer": customers["+919876543211"],
                "title": "Dell XPS 15 Video Editing Laptop",
                "source": LeadSource.PHONE,
                "stage": stages["quoted"],
                "assigned_to": demo_users["staff1"],
                "product_category": ProductCategory.LAPTOP,
                "budget_min": Decimal("120000"),
                "budget_max": Decimal("140000"),
                "notes": "Prefers OLED display, min 1TB SSD.",
            },
            {
                "customer": customers["+919876543212"],
                "title": "Office Workstations & Dual Monitors (5 units)",
                "source": LeadSource.WEBSITE,
                "stage": stages["contacted"],
                "assigned_to": demo_users["staff2"],
                "product_category": ProductCategory.DESKTOP_BUILD,
                "budget_min": Decimal("200000"),
                "budget_max": Decimal("300000"),
                "notes": "Company requirement for coding workstations.",
            },
            {
                "customer": customers["+919876543213"],
                "title": "Laptop Keyboard & Battery Replacement",
                "source": LeadSource.WALK_IN,
                "stage": stages["lost"],
                "assigned_to": demo_users["staff2"],
                "product_category": ProductCategory.REPAIR_SERVICE,
                "lost_reason_category": LostReasonCategory.PRICE_TOO_HIGH,
                "lost_reason_notes": "Customer opted for third-party repair shop.",
                "notes": "Spilled water on Lenovo ThinkPad keyboard.",
            },
            {
                "customer": customers["+919876543210"],
                "title": "Ultrawide 34-inch Curved Gaming Monitor",
                "source": LeadSource.WHATSAPP,
                "stage": stages["new"],
                "assigned_to": None,  # Unassigned lead for manager review
                "product_category": ProductCategory.PERIPHERALS,
                "budget_min": Decimal("40000"),
                "budget_max": Decimal("60000"),
                "notes": "Inquired on WhatsApp about Alienware / LG 144Hz monitors.",
            },
        ]

        created_leads = []
        for ld in leads_data:
            lead, _ = Lead.objects.get_or_create(
                customer=ld["customer"],
                title=ld["title"],
                defaults={
                    "source": ld["source"],
                    "stage": ld["stage"],
                    "assigned_to": ld["assigned_to"],
                    "product_category": ld["product_category"],
                    "budget_min": ld.get("budget_min"),
                    "budget_max": ld.get("budget_max"),
                    "deal_value": ld.get("deal_value"),
                    "lost_reason_category": ld.get("lost_reason_category", ""),
                    "lost_reason_notes": ld.get("lost_reason_notes", ""),
                    "notes": ld["notes"],
                    "created_by": demo_users["manager"],
                },
            )
            created_leads.append(lead)

        self.stdout.write(self.style.SUCCESS("✓ Sample leads created across pipeline stages."))

        # 5. Sample Activities and Follow-ups
        lead1 = created_leads[0]
        Activity.objects.get_or_create(
            lead=lead1,
            user=demo_users["staff1"],
            activity_type=ActivityType.CALL,
            title="Discussion on GPU stock and delivery dates",
            defaults={
                "notes": "Customer confirmed they will visit this Friday to place the deposit.",
                "occurred_at": now - timedelta(hours=3),
            },
        )

        # Overdue follow-up for staff1
        FollowUp.objects.get_or_create(
            lead=lead1,
            assigned_to=demo_users["staff1"],
            defaults={
                "note": "Follow up on cabinet color and deposit",
                "scheduled_at": now - timedelta(hours=24),
                "status": FollowUpStatus.PENDING,
            },
        )

        # Due today follow-up for staff1
        lead2 = created_leads[1]
        FollowUp.objects.get_or_create(
            lead=lead2,
            assigned_to=demo_users["staff1"],
            defaults={
                "note": "Send revised quotation with 3-year warranty option",
                "scheduled_at": now + timedelta(hours=2),
                "status": FollowUpStatus.PENDING,
            },
        )

        # Notifications
        Notification.objects.get_or_create(
            user=demo_users["staff1"],
            dedupe_key="demo_overdue_lead1",
            defaults={
                "notification_type": NotificationType.OVERDUE_FOLLOW_UP,
                "title": "Overdue Follow-up: Rajesh Kumar",
                "message": "Follow-up 'Follow up on cabinet color and deposit' is overdue.",
                "lead": lead1,
            },
        )

        Notification.objects.get_or_create(
            user=demo_users["manager"],
            dedupe_key="demo_unassigned_lead5",
            defaults={
                "notification_type": NotificationType.NEW_LEAD,
                "title": "Unassigned Lead: Ultrawide Monitor",
                "message": "A new WhatsApp inquiry is unassigned. Please assign to staff.",
                "lead": created_leads[4],
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ Activities, follow-ups, and notifications seeded."))
        self.stdout.write(self.style.SUCCESS("\n🎉 Demo seed complete!"))
