from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q
from .models import SavingsCycle, SavingsEntry
from authentication.models import MemberProfile
from .serializers import (
    SavingsCycleSerializer, CreateSavingsCycleSerializer,
    SavingsEntrySerializer, CreateSavingsEntrySerializer
)
from .sms_service import SMSService
import logging

logger = logging.getLogger(__name__)


# ============================================
# FIXED VIEWSETS - Added *args, **kwargs
# ============================================

class SavingsEntryViewSet(viewsets.ModelViewSet):
    """API for managing savings entries"""
    
    permission_classes = [IsAuthenticated]
    queryset = SavingsEntry.objects.select_related('member', 'cycle').all()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateSavingsEntrySerializer
        return SavingsEntrySerializer
    
    def list(self, request, *args, **kwargs):
        """GET /api/savings/"""
        queryset = self.get_queryset()
        
        # Filter by member
        member_id = request.query_params.get('member')
        if member_id:
            queryset = queryset.filter(member_id=member_id)
        
        # Filter by cycle
        cycle_id = request.query_params.get('cycle')
        if cycle_id:
            queryset = queryset.filter(cycle_id=cycle_id)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        """POST /api/savings/"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(created_by=request.user)
        
        # Send SMS notification (async, don't fail if SMS fails)
        try:
            success, message = SMSService.send_savings_notification(
                member=entry.member,
                amount=entry.amount,
                date=entry.date
            )
            
            if success:
                logger.info(f"SMS sent for savings entry {entry.id}")
            else:
                logger.warning(f"SMS failed for savings {entry.id}: {message}")
        
        except Exception as e:
            logger.error(f"SMS exception for savings {entry.id}: {str(e)}")
        
        return Response(
            SavingsEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED
        )
    
    def retrieve(self, request, *args, **kwargs):
        """GET /api/savings/{id}/"""
        entry = self.get_object()
        serializer = self.get_serializer(entry)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        """PUT /api/savings/{id}/"""
        entry = self.get_object()
        serializer = CreateSavingsEntrySerializer(entry, data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        
        # Send SMS notification for update
        try:
            SMSService.send_savings_update_notification(
                member=entry.member,
                amount=entry.amount,
                date=entry.date
            )
        except Exception as e:
            logger.error(f"SMS update notification failed: {str(e)}")
        
        return Response(SavingsEntrySerializer(entry).data)
    
    def destroy(self, request, *args, **kwargs):
        """DELETE /api/savings/{id}/"""
        entry = self.get_object()
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavingsCycleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing savings cycles"""
    
    permission_classes = [IsAuthenticated]
    queryset = SavingsCycle.objects.all()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateSavingsCycleSerializer
        return SavingsCycleSerializer
    
    def list(self, request, *args, **kwargs):
        """GET /api/cycles/"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        """POST /api/cycles/"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        
        return Response(
            SavingsCycleSerializer(cycle).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """GET /api/cycles/active/"""
        cycle = SavingsCycle.objects.filter(status='active').first()
        if not cycle:
            return Response(
                {'detail': 'No active cycle found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(cycle)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """POST /api/cycles/{id}/close/"""
        cycle = self.get_object()
        
        if cycle.status != 'active':
            return Response(
                {'detail': 'Only active cycles can be closed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        cycle.status = 'closed'
        cycle.save()
        
        serializer = self.get_serializer(cycle)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """GET /api/cycles/statistics/"""
        return Response({
            'active': SavingsCycle.objects.filter(status='active').count(),
            'upcoming': SavingsCycle.objects.filter(status='upcoming').count(),
            'closed': SavingsCycle.objects.filter(status='closed').count()
        })


# ============================================
# NEW VIEWS FOR "VIEW SAVINGS" PAGE
# ============================================

class MembersListWithSavingsView(APIView):
    """
    GET /api/view-savings/members/
    
    Get all members with their total savings in active cycle
    For the members table in View Savings page
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get search query if provided
        search_query = request.GET.get('search', '').strip()
        
        # Get active cycle
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            return Response({
                'members': [],
                'total_count': 0,
                'cycle_name': None,
                'error': 'No active cycle found'
            })
        
        # Get all active members
        members = MemberProfile.objects.filter(is_active_member=True)
        
        # Apply search filter if provided
        if search_query:
            members = members.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(membership_id__icontains=search_query)
            )
        
        # Get savings for each member
        result = []
        for member in members:
            # Calculate total savings for this member in active cycle
            total_savings = SavingsEntry.objects.filter(
                member=member,
                cycle=active_cycle
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            result.append({
                'id': member.id,
                'name': f"{member.user.first_name} {member.user.last_name}",
                'first_name': member.user.first_name,
                'last_name': member.user.last_name,
                'membership_id': member.membership_id,
                'total_savings': float(total_savings),
                'initials': f"{member.user.first_name[0]}{member.user.last_name[0]}".upper() if member.user.first_name and member.user.last_name else "??"
            })
        
        # Sort by total savings (highest first)
        result.sort(key=lambda x: x['total_savings'], reverse=True)
        
        return Response({
            'members': result,
            'total_count': len(result),
            'cycle_name': active_cycle.name
        })


class MemberSavingsDetailView(APIView):
    """
    GET /api/view-savings/members/{member_id}/
    
    Get detailed savings information for a specific member
    Shows total savings this month and all entries
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, member_id):
        try:
            # Get the member
            member = MemberProfile.objects.select_related('user').get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({
                'error': 'Member not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get active cycle
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            return Response({
                'error': 'No active cycle found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get all entries for this member in the active cycle
        entries = SavingsEntry.objects.filter(
            member=member,
            cycle=active_cycle
        ).order_by('-date', '-created_at')
        
        # Calculate total for this month/cycle
        total_this_month = entries.aggregate(total=Sum('amount'))['total'] or 0
        
        # Calculate TOTAL LIFETIME savings (across ALL cycles)
        total_lifetime = SavingsEntry.objects.filter(
            member=member
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Format entries
        entries_list = []
        for entry in entries:
            entries_list.append({
                'id': entry.id,
                'date': entry.date.strftime('%b %d, %Y'),  # "Nov 2, 2025"
                'amount': float(entry.amount),
                'comment': entry.comment or ''
            })
        
        return Response({
            'member': {
                'id': member.id,
                'name': f"{member.user.first_name} {member.user.last_name}",
                'first_name': member.user.first_name,
                'last_name': member.user.last_name,
                'membership_id': member.membership_id,
                'initials': f"{member.user.first_name[0]}{member.user.last_name[0]}".upper() if member.user.first_name and member.user.last_name else "??"
            },
            'cycle': {
                'name': active_cycle.name,
                'month': active_cycle.start_date.strftime('%B %Y')  # "November 2025"
            },
            'total_lifetime': float(total_lifetime),  # Grand total (all time)
            'total_this_month': float(total_this_month),  # This cycle only
            'entries_count': entries.count(),
            'entries': entries_list
        })


class MemberSavingsHistoryView(APIView):
    """
    GET /api/view-savings/members/{member_id}/history/
    
    Get savings history across all cycles for a member
    Optional: For viewing historical data
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, member_id):
        try:
            member = MemberProfile.objects.select_related('user').get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({
                'error': 'Member not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get all cycles with this member's savings
        cycles = SavingsCycle.objects.filter(
            savings_entries__member=member
        ).distinct().order_by('-start_date')
        
        history = []
        for cycle in cycles:
            # Get total for this cycle
            cycle_total = SavingsEntry.objects.filter(
                member=member,
                cycle=cycle
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            # Get entry count
            entry_count = SavingsEntry.objects.filter(
                member=member,
                cycle=cycle
            ).count()
            
            history.append({
                'cycle_name': cycle.name,
                'start_date': cycle.start_date.isoformat(),
                'end_date': cycle.end_date.isoformat(),
                'status': cycle.status,
                'total_saved': float(cycle_total),
                'entries_count': entry_count
            })
        
        # Calculate grand total across all cycles
        grand_total = SavingsEntry.objects.filter(
            member=member
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'member': {
                'id': member.id,
                'name': f"{member.user.first_name} {member.user.last_name}",
                'membership_id': member.membership_id
            },
            'grand_total': float(grand_total),
            'total_cycles': cycles.count(),
            'history': history
        })