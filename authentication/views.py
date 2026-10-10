from rest_framework import status, generics, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login, logout
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated

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



def _to_int(value):
    """int(value) or None. Rejects bools and junk."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
 
 
class CollectorViewSet(viewsets.ModelViewSet):
    """Admin-managed collectors.
 
    Members are attached to a collector when they are created. This
    viewset also lets the admin edit a collector, delete it (only when it
    has no members), and move members between collectors.
    """
 
    permission_classes = [IsAuthenticated]
    serializer_class = CollectorSerializer
 
    def get_permissions(self):
        # Destructive / bulk actions: staff only. Everything else keeps
        # the permissions you already had.
        if self.action in ('destroy', 'reassign_members'):
            return [IsAuthenticated(), IsAdminUser()]
        return super().get_permissions()
 
    def get_queryset(self):
        # Subquery instead of a reverse-relation Count, so this works
        # whatever related_name MemberProfile.collector uses.
        member_count = (
            MemberProfile.objects
            .filter(collector=OuterRef('pk'))
            .order_by()
            .values('collector')
            .annotate(c=Count('pk'))
            .values('c')
        )
        queryset = Collector.objects.annotate(
            member_total=Coalesce(Subquery(member_count, output_field=IntegerField()), 0)
        )
        if self.action == 'list' and self.request.query_params.get('active_only', 'true') == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset
 
    # ---------------------------------------------------------- create
    def create(self, request, *args, **kwargs):
        """POST /api/auth/collectors/ - {"name": "...", "phone_number": "..."}"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collector = serializer.save(created_by=request.user)
        return Response(CollectorSerializer(collector).data, status=status.HTTP_201_CREATED)
 
    # ---------------------------------------------------------- delete
    def destroy(self, request, *args, **kwargs):
        """DELETE /api/auth/collectors/{id}/
 
        Refused while any member (active or inactive) is still attached.
        The check runs on the server inside a transaction, with the
        member rows locked, so a member cannot slip in between the check
        and the delete.
        """
        collector = self.get_object()
 
        with transaction.atomic():
            collector = Collector.objects.select_for_update().get(pk=collector.pk)
            attached = list(
                MemberProfile.objects.select_for_update()
                .filter(collector=collector)
                .values_list('pk', flat=True)
            )
            if attached:
                return Response(
                    {
                        'error': (
                            f'Cannot delete "{collector.name}": it still has '
                            f'{len(attached)} member(s). Move them to another '
                            f'collector first.'
                        ),
                        'members_count': len(attached),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            collector.delete()
 
        return Response(status=status.HTTP_204_NO_CONTENT)
 
    # --------------------------------------------------------- members
    @action(detail=True, methods=['get'], url_path='members')
    def members(self, request, pk=None):
        """GET /api/auth/collectors/{id}/members/?search=<name|membership id|phone>
 
        Returns EVERY member of this collector (no paging), so the page
        can show them all and let the admin edit each row.
        """
        collector = self.get_object()
        queryset = (
            MemberProfile.objects
            .filter(collector=collector)
            .select_related('user')
            .order_by('user__first_name', 'user__last_name')
        )
 
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(membership_id__icontains=search) |
                Q(user__phone_number__icontains=search)
            )
 
        results = [{
            'id': m.id,
            'name': m.user.get_full_name(),
            'membership_id': m.membership_id,
            'phone_number': getattr(m.user, 'phone_number', None),
            'is_active_member': m.is_active_member,
            'collector_id': collector.id,
        } for m in queryset]
 
        return Response({
            'collector': {'id': collector.id, 'name': collector.name},
            'count': len(results),
            'results': results,
        })
 
    # ------------------------------------------------------ reassign
    @action(detail=True, methods=['post'], url_path='reassign-members')
    def reassign_members(self, request, pk=None):
        """POST /api/auth/collectors/{id}/reassign-members/
 
        Three ways to call it (all-or-nothing, in one transaction):
 
        A) Move ALL members of this collector:
           {"target_collector": 7, "all": true}
 
        B) Move SELECTED members to one collector:
           {"target_collector": 7, "member_ids": [11, 12, 15]}
 
        C) One by one, each member to its own collector (save-all button):
           {"moves": [{"member_id": 11, "collector_id": 7},
                      {"member_id": 12, "collector_id": 9}]}
 
        Every member must currently belong to {id}; if the page is stale
        the whole request is rejected and nothing is changed.
        """
        source = self.get_object()
        data = request.data
 
        # ---- 1. Build the wanted moves as {member_id: target_collector_id}
        wanted = {}
        moves = data.get('moves')
 
        if moves is not None:
            if not isinstance(moves, list) or not moves:
                return Response({'error': '"moves" must be a non-empty list.'},
                                status=status.HTTP_400_BAD_REQUEST)
            for item in moves:
                member_id = _to_int(item.get('member_id')) if isinstance(item, dict) else None
                target_id = _to_int(item.get('collector_id')) if isinstance(item, dict) else None
                if member_id is None or target_id is None:
                    return Response(
                        {'error': 'Each move needs integer "member_id" and "collector_id".'},
                        status=status.HTTP_400_BAD_REQUEST)
                wanted[member_id] = target_id
        else:
            target_id = _to_int(data.get('target_collector'))
            if target_id is None:
                return Response({'error': '"target_collector" is required.'},
                                status=status.HTTP_400_BAD_REQUEST)
 
            if str(data.get('all', '')).lower() == 'true':
                member_ids = list(
                    MemberProfile.objects.filter(collector=source).values_list('pk', flat=True)
                )
            else:
                raw_ids = data.get('member_ids')
                if not isinstance(raw_ids, list) or not raw_ids:
                    return Response(
                        {'error': 'Send "member_ids" (list) or "all": true.'},
                        status=status.HTTP_400_BAD_REQUEST)
                member_ids = [_to_int(i) for i in raw_ids]
                if None in member_ids:
                    return Response({'error': '"member_ids" must be integers.'},
                                    status=status.HTTP_400_BAD_REQUEST)
            wanted = {mid: target_id for mid in member_ids}
 
        # Moving a member to the collector they already have is a no-op.
        wanted = {mid: tid for mid, tid in wanted.items() if tid != source.pk}
        if not wanted:
            return Response({'error': 'Nothing to move.'}, status=status.HTTP_400_BAD_REQUEST)
 
        with transaction.atomic():
            # ---- 2. Members must really belong to this collector (locked)
            found = set(
                MemberProfile.objects.select_for_update()
                .filter(collector=source, pk__in=wanted.keys())
                .values_list('pk', flat=True)
            )
            missing = sorted(set(wanted) - found)
            if missing:
                return Response(
                    {
                        'error': ('Some members are no longer in this collector. '
                                  'Refresh the page and try again. Nothing was changed.'),
                        'member_ids': missing,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
 
            # ---- 3. Target collectors must exist and be active
            target_ids = set(wanted.values())
            valid_targets = set(
                Collector.objects.filter(pk__in=target_ids, is_active=True)
                .values_list('pk', flat=True)
            )
            bad_targets = sorted(target_ids - valid_targets)
            if bad_targets:
                return Response(
                    {
                        'error': 'Target collector not found or inactive. Nothing was changed.',
                        'collector_ids': bad_targets,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
 
            # ---- 4. Apply: one UPDATE per target collector
            extra = {}
            if any(f.name == 'updated_at' for f in MemberProfile._meta.get_fields()):
                extra['updated_at'] = timezone.now()  # .update() skips auto_now
 
            by_target = {}
            for member_id, tid in wanted.items():
                by_target.setdefault(tid, []).append(member_id)
            for tid, ids in by_target.items():
                MemberProfile.objects.filter(pk__in=ids).update(collector_id=tid, **extra)
 
            remaining = MemberProfile.objects.filter(collector=source).count()
 
        return Response({
            'moved': len(wanted),
            'source': {'id': source.id, 'name': source.name},
            'remaining_members': remaining,
            'can_delete_source': remaining == 0,
        })

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