from django.urls import path

from .views import AuthCheckView, PasswordCheckView

urlpatterns = [
    path("auth/check", AuthCheckView.as_view(), name="auth-check"),
    path("password/check", PasswordCheckView.as_view(), name="password-check"),
]
