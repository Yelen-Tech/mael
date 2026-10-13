from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", include("modules.reputation.urls")),
    path("v1/", include("modules.authguard.urls")),
]
