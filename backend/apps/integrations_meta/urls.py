from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.integrations_meta.views import MetaWebhookLogViewSet, MetaWebhookView

router = DefaultRouter()
router.register(r"integrations/meta/logs", MetaWebhookLogViewSet, basename="meta-webhook-log")

urlpatterns = [
    path("integrations/meta/webhook/", MetaWebhookView.as_view(), name="meta-webhook"),
    path("", include(router.urls)),
]
