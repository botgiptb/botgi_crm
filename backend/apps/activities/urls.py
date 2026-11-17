from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.activities.views import ActivityViewSet, FollowUpViewSet

router = DefaultRouter()
router.register(r"activities", ActivityViewSet, basename="activity")
router.register(r"follow-ups", FollowUpViewSet, basename="follow-up")

urlpatterns = [
    path("", include(router.urls)),
]
