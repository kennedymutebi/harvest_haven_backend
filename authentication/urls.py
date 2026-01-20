from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    SignUpView, LoginView, VerifyOTPView, ResendOTPView, LogoutView, 
    UserProfileView, ChangePasswordView, PasswordResetRequestView,
    ApproveUserView, CheckApprovalStatusView
)

app_name = 'authentication'

urlpatterns = [
    # Registration & Verification
    path('signup/', SignUpView.as_view(), name='signup'),
    
    path('check-status/', CheckApprovalStatusView.as_view(), name='check-status'),
    
    # Admin Approval
    path('approve-user/<str:token>/', ApproveUserView.as_view(), name='approve-user'),
    
    # Login with OTP
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('logout/', LogoutView.as_view(), name='logout'),
    
    # Profile & Password
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('forgot-password/', PasswordResetRequestView.as_view(), name='forgot-password'),
    
    # JWT Token
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]