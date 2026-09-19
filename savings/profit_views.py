"""
savings/profit_views.py  (NEW FILE)

The per-member profit API the client asked for. Add these two views to
savings/views.py (or keep as a separate file and import into urls.py -
either works; shown separate here to avoid a large diff on your existing
views.py).

Replaces reliance on SavingsCycle.total_profit() (interest_rate % of the
whole cycle's deposits) with the tiered per-member charge from Section 7.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import SavingsCycle
from authentication.models import MemberProfile
from .infrastructure import get_member_profit_for_cycle, get_all_member_profits_for_cycle


def _resolve_cycle(request):
    """Shared helper: ?cycle_id=<id> or defaults to the active cycle -
    same convention already used by CycleExportView etc."""
    cycle_id = request.query_params.get('cycle_id')
    if cycle_id:
        return SavingsCycle.objects.filter(id=cycle_id).first()
    return SavingsCycle.objects.filter(status='active').first()


class MemberProfitView(APIView):
    """
    GET /api/savings/members/<member_id>/profit/?cycle_id=<id>

    One member's monthly charge for a given cycle (defaults to the
    active cycle), based on the Section 7 tiered table.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):
        try:
            member = MemberProfile.objects.get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)

        cycle = _resolve_cycle(request)
        if not cycle:
            return Response({'error': 'No matching cycle found'}, status=status.HTTP_404_NOT_FOUND)

        line = get_member_profit_for_cycle(member.id, cycle)

        return Response({
            'member_id': member.id,
            'member_name': member.user.get_full_name(),
            'membership_id': member.membership_id,
            'cycle': {'id': cycle.id, 'name': cycle.name},
            'collected_this_month': line.collected_this_month.to_float(),
            'charge': line.charge.to_float(),
        })


class CycleProfitView(APIView):
    """
    GET /api/savings/profit/?cycle_id=<id>

    Every member's monthly charge for a given cycle (defaults to the
    active cycle), plus the total - this is what the dashboard's "Total
    Profit" figure should be built from going forward, instead of
    SavingsCycle.total_profit()'s interest_rate percentage.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cycle = _resolve_cycle(request)
        if not cycle:
            return Response({'error': 'No matching cycle found'}, status=status.HTTP_404_NOT_FOUND)

        lines = get_all_member_profits_for_cycle(cycle)
        member_ids = [line.member_id for line in lines]
        members_by_id = {
            m.id: m for m in MemberProfile.objects.filter(id__in=member_ids).select_related('user')
        }

        results = []
        total_profit = 0.0
        for line in lines:
            member = members_by_id.get(line.member_id)
            total_profit += line.charge.to_float()
            results.append({
                'member_id': line.member_id,
                'member_name': member.user.get_full_name() if member else None,
                'membership_id': member.membership_id if member else None,
                'collected_this_month': line.collected_this_month.to_float(),
                'charge': line.charge.to_float(),
            })

        # Highest charge first - surfaces the SACCO's biggest contributors.
        results.sort(key=lambda r: r['charge'], reverse=True)

        return Response({
            'cycle': {'id': cycle.id, 'name': cycle.name},
            'total_profit': total_profit,
            'members_charged': len([r for r in results if r['charge'] > 0]),
            'results': results,
        })