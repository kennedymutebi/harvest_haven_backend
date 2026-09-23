from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone
from datetime import timedelta
from savings.models import SavingsCycle, SavingsEntry
from authentication.models import MemberProfile
from savings.infrastructure import get_cycle_total_profit, get_all_member_profits_for_cycle
from savings_domain.profit_service import MemberProfitCalculator

class DashboardView(APIView):
    """Main dashboard statistics"""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get active cycle
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            return Response({
                'error': 'No active cycle found',
                'total_savings': 0,
                'total_profit': 0,
                'profit_margin': 0,
                'active_members': 0,
                'new_members_this_month': 0,
                'growth_percentage': 0
            })
        
        # Total savings
        total_savings = active_cycle.total_savings()
        
        # Total profit
        # Total profit
        total_profit = get_cycle_total_profit(active_cycle)
        
        # Active members
        active_members = MemberProfile.objects.filter(is_active_member=True).count()
        
        # New members THIS MONTH
        current_month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_members = MemberProfile.objects.filter(
            date_joined__gte=current_month_start
        ).count()
        
        # Calculate growth percentage (compare with last cycle)
        last_cycle = SavingsCycle.objects.filter(
            status='closed'
        ).order_by('-end_date').first()
        
        growth_percentage = 0
        if last_cycle:
            last_total = last_cycle.total_savings()
            if last_total > 0:
                growth_percentage = ((total_savings - last_total) / last_total) * 100
        
        return Response({
            'total_savings': float(total_savings),
            'total_profit': float(total_profit),
            'profit_margin': float(active_cycle.interest_rate),
            'active_members': active_members,
            'new_members_this_month': new_members,
            'growth_percentage': round(growth_percentage, 1),
            'current_cycle': {
                'id': active_cycle.id,
                'name': active_cycle.name,
                'start_date': active_cycle.start_date,
                'end_date': active_cycle.end_date
            }
        })


class SavingsTrendView(APIView):
    """Savings and profit trend by MONTH (last 7 months)"""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get data for last 7 months
        seven_months_ago = timezone.now() - timedelta(days=210)
        
        monthly_data = SavingsEntry.objects.filter(
            date__gte=seven_months_ago
        ).annotate(
            month=TruncMonth('date')
        ).values('month').annotate(
            total_savings=Sum('amount')
        ).order_by('month')
        
        trend_data = []
        for item in monthly_data:
            cycle = SavingsCycle.objects.filter(
                start_date__lte=item['month'],
                end_date__gte=item['month']
            ).first()

            savings = item['total_savings'] or 0
            profit = float(get_cycle_total_profit(cycle)) if cycle else 0.0

            trend_data.append({
                'month': item['month'].strftime('%b'),
                'savings': float(savings),
                'profit': round(profit, 2)
            })
        
        return Response(trend_data)


class WeeklyDepositView(APIView):
    """DAILY deposit activity for current week"""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            return Response([])
        
        # Get start of current week (Monday)
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        
        # Get daily deposits for this week
        daily_data = SavingsEntry.objects.filter(
            cycle=active_cycle,
            date__gte=week_start
        ).annotate(
            day=TruncDay('date')
        ).values('day').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('day')
        
        # Create result with all 7 days (even if no deposits)
        result = []
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        for i in range(7):
            day_date = week_start + timedelta(days=i)
            day_data = next((d for d in daily_data if d['day'] == day_date), None)
            
            result.append({
                'day': days[i],
                'amount': float(day_data['total']) if day_data else 0,
                'deposits': day_data['count'] if day_data else 0
            })
        
        return Response(result)


class RecentTransactionsView(APIView):
    """Recent transactions list (last 10) - MATCHED TO YOUR MODEL"""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            return Response([])
        
        # Get last 10 entries - using YOUR actual model fields
        transactions = SavingsEntry.objects.filter(
            cycle=active_cycle
        ).select_related('member__user').order_by('-date', '-created_at')[:10]
        
        result = []
        for txn in transactions:
            result.append({
                'member': {
                    'first_name': txn.member.user.first_name,
                    'last_name': txn.member.user.last_name,
                },
                'type': 'Deposit',  # All entries are deposits (no withdrawals)
                'amount': float(txn.amount),
                'status': 'completed',  # All saved entries are completed
                'date': txn.date.isoformat(),
                'comment': txn.comment or ''
            })
        
        return Response(result)


class TopSaversView(APIView):
    """Top 5 savers leaderboard - MATCHED TO YOUR MODEL"""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            return Response([])
        
        # Get members with their total savings in active cycle
        top_savers = SavingsEntry.objects.filter(
            cycle=active_cycle
        ).values(
            'member__user__first_name',
            'member__user__last_name',
            'member__id'
        ).annotate(
            total_savings=Sum('amount')
        ).order_by('-total_savings')[:5]
        
        result = []
        for idx, saver in enumerate(top_savers, start=1):
            result.append({
                'rank': idx,
                'name': f"{saver['member__user__first_name']} {saver['member__user__last_name']}",
                'total_savings': float(saver['total_savings'])
            })
        
        return Response(result)

