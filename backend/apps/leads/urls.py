from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.leads.views import (
    CustomerViewSet,
    LeadViewSet,
    StageViewSet,
    UnprocessedMetaLeadViewSet,
)

router = DefaultRouter()
router.register(r"stages", StageViewSet, basename="stage")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"leads", LeadViewSet, basename="lead")
router.register(r"meta-unprocessed", UnprocessedMetaLeadViewSet, basename="meta-unprocessed")

urlpatterns = [
    path("", include(router.urls)),
]
