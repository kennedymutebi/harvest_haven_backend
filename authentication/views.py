from rest_framework import status, generics, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login, logout
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import User, MemberProfile, PendingApproval, PasswordResetToken, Collector
from .serializers import (
    SignUpSerializer, LoginSerializer, UserSerializer,
    ChangePasswordSerializer, PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
    MemberProfileSerializer,CollectorSerializer
)
from .utils import (
    send_admin_approval_email,
    send_approval_status_email, send_password_reset_email,
)


class SignUpView(generics.CreateAPIView):
    """User registration endpoint"""

    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = SignUpSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Create pending approval
        approval = PendingApproval.objects.create(user=user)

        # Send email to admin for approval
        try:
            send_admin_approval_email(user, approval)
        except Exception as e:
            print(f"Failed to send admin approval email: {e}")

        return Response({
            'message': 'Registration successful! Your account is pending admin approval.',
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class ApproveUserView(APIView):
    """Admin approval endpoint"""

    permission_classes = [AllowAny]  # Replace with IsAdminUser in production

    def get(self, request, token):
        action = request.GET.get('action', 'approve')

        try:
            approval = PendingApproval.objects.get(approval_token=token, status='pending')
            user = approval.user

            if action == 'approve':
                user.is_admin_approved = True
                user.save()

                approval.status = 'approved'
                approval.reviewed_at = timezone.now()
                approval.reviewed_by = request.GET.get('admin_email', 'admin')
                approval.save()

                try:
                    send_approval_status_email(user, approved=True)
                except Exception as e:
                    print(f"Failed to send approval email: {e}")

                return Response({
                    'message': f'User {user.get_full_name()} has been approved successfully!',
                    'user': UserSerializer(user).data
                }, status=status.HTTP_200_OK)

            elif action == 'reject':
                reason = request.GET.get('reason', 'Your registration did not meet our requirements.')

                approval.status = 'rejected'
                approval.reviewed_at = timezone.now()
                approval.reviewed_by = request.GET.get('admin_email', 'admin')
                approval.rejection_reason = reason
                approval.save()

                try:
                    send_approval_status_email(user, approved=False, reason=reason)
                except Exception as e:
                    print(f"Failed to send rejection email: {e}")

                return Response({
                    'message': f'User {user.get_full_name()} has been rejected.',
                }, status=status.HTTP_200_OK)

            else:
                return Response({
                    'error': 'Invalid action. Use "approve" or "reject".'
                }, status=status.HTTP_400_BAD_REQUEST)

        except PendingApproval.DoesNotExist:
            return Response({
                'error': 'Invalid or already processed approval token.'
            }, status=status.HTTP_404_NOT_FOUND)


class LoginView(APIView):
    """User login endpoint - email + password, returns JWT tokens directly"""

    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']

        login(request, user)
        refresh = RefreshToken.for_user(user)

        return Response({
            'user': UserSerializer(user).data,
            'message': 'Login successful',
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)}
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            logout(request)
            return Response({'message': 'Logout successful'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()

        return Response({'message': 'Password changed successfully'}, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    """Step 1 — User submits email, receives reset link"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)

            # Invalidate all previous unused tokens
            PasswordResetToken.objects.filter(
                user=user, is_used=False
            ).update(is_used=True)

            # Create fresh token
            reset_token = PasswordResetToken.objects.create(user=user)

            try:
                send_password_reset_email(user, reset_token)
            except Exception as e:
                print(f"Failed to send reset email: {e}")

        except User.DoesNotExist:
            pass  # Silent — never reveal whether email exists

        # Always return the same response
        return Response(
            {'message': 'If that email is registered, a reset link has been sent.'},
            status=status.HTTP_200_OK
        )


class PasswordResetConfirmView(APIView):
    """Step 2 — User submits token + new password from the email link"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token_value  = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        try:
            reset_token = PasswordResetToken.objects.select_related('user').get(
                token=token_value
            )
        except PasswordResetToken.DoesNotExist:
            return Response(
                {'error': 'Invalid reset link.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not reset_token.is_valid():
            return Response(
                {'error': 'This reset link has expired or already been used.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = reset_token.user
        user.set_password(new_password)
        user.save()

        reset_token.is_used = True
        reset_token.save()

        return Response(
            {'message': 'Password reset successful. You can now log in.'},
            status=status.HTTP_200_OK
        )



class CollectorViewSet(viewsets.ModelViewSet):
    """Admin-managed collectors. Members are attached to a Collector
    via a dropdown when they're created — this endpoint powers that
    dropdown (GET /api/auth/collectors/) and lets the admin add new
    collectors (POST /api/auth/collectors/)."""

    permission_classes = [IsAuthenticated]
    serializer_class = CollectorSerializer

    def get_queryset(self):
        queryset = Collector.objects.all()
        if self.action == 'list' and self.request.query_params.get('active_only', 'true') == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset

    def create(self, request, *args, **kwargs):
        """POST /api/auth/collectors/  — {"name": "...", "phone_number": "..."}"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collector = serializer.save(created_by=request.user)
        return Response(CollectorSerializer(collector).data, status=status.HTTP_201_CREATED)

class CheckApprovalStatusView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')

        try:
            user = User.objects.get(email=email)
            approval = PendingApproval.objects.filter(user=user).first()

            return Response({
                'email': user.email,
                'is_admin_approved': user.is_admin_approved,
                'can_login': user.can_login(),
                'approval_status': approval.status if approval else 'unknown',
                'message': self._get_status_message(user, approval)
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    def _get_status_message(self, user, approval):
        if not user.is_admin_approved:
            if approval and approval.status == 'rejected':
                return f'Your registration was rejected. Reason: {approval.rejection_reason}'
            return 'Your account is pending admin approval.'
        elif user.can_login():
            return 'Your account is active. You can now log in.'
        else:
            return 'Your account is inactive. Please contact support.'