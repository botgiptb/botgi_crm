from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.leads.urls")),
    path("api/", include("apps.activities.urls")),
    path("api/", include("apps.integrations_meta.urls")),
]
