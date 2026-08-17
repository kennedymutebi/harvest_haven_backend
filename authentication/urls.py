from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    PasswordResetConfirmView, SignUpView, LoginView, LogoutView,
    UserProfileView, ChangePasswordView, PasswordResetRequestView,
    ApproveUserView, CheckApprovalStatusView, CollectorViewSet
)

app_name = 'authentication'

router = DefaultRouter()
router.register(r'collectors', CollectorViewSet, basename='collector')

urlpatterns = [
    # Registration & Verification
    path('signup/', SignUpView.as_view(), name='signup'),

    path('check-status/', CheckApprovalStatusView.as_view(), name='check-status'),

    # Admin Approval
    path('approve-user/<str:token>/', ApproveUserView.as_view(), name='approve-user'),

    # Login - email + password, no OTP
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Profile & Password
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('forgot-password/',         PasswordResetRequestView.as_view(),  name='forgot-password'),
    path('reset-password/confirm/',  PasswordResetConfirmView.as_view(),  name='reset-password-confirm'),

    # JWT Token
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),

    # Collectors (admin-managed, no login)
    path('', include(router.urls)),
]