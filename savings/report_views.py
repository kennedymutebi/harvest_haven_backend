"""
savings/report_views.py

JSON endpoints for the reports UI. These replace pdf_exports.py and the
Excel side of exports.py: Django's only job now is to hand back numbers
from reporting.py — every PDF/Excel is built client-side from this data,
so backend and frontend can never disagree about a total.
"""

from decimal import Decimal

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .reporting import (
    get_cycle_summary_for_all_members,
    get_member_lifetime_history,
    get_collector_summary,
)
from .models import SavingsCycle
from authentication.models import MemberProfile, Collector


def _num(value):
    """Decimal/None -> JSON-safe float. Keep this centralized so every
    endpoint serializes money the same way."""
    if value is None:
        return 0
    return float(Decimal(value))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cycle_report_json(request):
    cycle_id = request.query_params.get('cycle_id')
    if cycle_id:
        try:
            cycle = SavingsCycle.objects.get(id=cycle_id)
        except SavingsCycle.DoesNotExist:
            return Response({'error': 'Cycle not found'}, status=404)
    else:
        cycle = SavingsCycle.objects.filter(status='active').first()
        if not cycle:
            return Response({'error': 'No active cycle found'}, status=404)

    members_qs = MemberProfile.objects.filter(is_active_member=True).select_related('user')
    summaries = get_cycle_summary_for_all_members(cycle, members_qs)

    members = []
    for s in summaries:
        member = s['member']
        members.append({
            'membership_id': member.membership_id,
            'member_name': member.user.get_full_name(),
            'carry_forward': _num(s['carry_forward']),
            'savings': _num(s['savings']),
            'withdrawals': _num(s['withdrawals']),
            'closing_balance': _num(s['closing_balance']),
            'returned_amount': _num(s['returned_amount']),
        })

    return Response({
        'cycle_name': cycle.name,
        'start_date': cycle.start_date.isoformat(),
        'end_date': cycle.end_date.isoformat() if cycle.end_date else None,
        'status': cycle.get_status_display(),
        'members': members,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def member_statement_json(request, member_id):
    try:
        member = MemberProfile.objects.select_related('user').get(id=member_id)
    except MemberProfile.DoesNotExist:
        return Response({'error': 'Member not found'}, status=404)

    history = get_member_lifetime_history(member)

    return Response({
        'member_name': member.user.get_full_name(),
        'membership_id': member.membership_id,
        'history': [
            {
                'cycle_name': s['cycle'].name,
                'carry_forward': _num(s['carry_forward']),
                'savings': _num(s['savings']),
                'withdrawals': _num(s['withdrawals']),
                'closing_balance': _num(s['closing_balance']),
                'returned_amount': _num(s['returned_amount']),
            }
            for s in history
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def collector_summary_json(request, collector_id):
    try:
        collector = Collector.objects.get(id=collector_id)
    except Collector.DoesNotExist:
        return Response({'error': 'Collector not found'}, status=404)

    cycle = None
    cycle_id = request.query_params.get('cycle_id')
    if cycle_id:
        try:
            cycle = SavingsCycle.objects.get(id=cycle_id)
        except SavingsCycle.DoesNotExist:
            return Response({'error': 'Cycle not found'}, status=404)

    members_qs = MemberProfile.objects.filter(collector=collector)
    summary = get_collector_summary(collector, members_qs, cycle=cycle)

    return Response({
        'collector_name': collector.name,
        'cycle_name': cycle.name if cycle else None,
        'member_count': summary['member_count'],
        'total_savings': _num(summary['total_savings']),
        'total_withdrawals': _num(summary['total_withdrawals']),
        'total_balance': _num(summary['total_balance']),
        'amount_to_be_returned': _num(summary['amount_to_be_returned']),
        'amount_carried_forward': _num(summary['amount_carried_forward']),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def all_collectors_summary_json(request):
    """Same per-collector numbers as collector_summary_json, just looped —
    kept as one endpoint so the 'all collectors' sheet can never disagree
    with an individual collector's PDF/Excel."""
    cycle = None
    cycle_id = request.query_params.get('cycle_id')
    if cycle_id:
        try:
            cycle = SavingsCycle.objects.get(id=cycle_id)
        except SavingsCycle.DoesNotExist:
            return Response({'error': 'Cycle not found'}, status=404)

    rows = []
    for collector in Collector.objects.all():
        members_qs = MemberProfile.objects.filter(collector=collector)
        summary = get_collector_summary(collector, members_qs, cycle=cycle)
        rows.append({
            'collector_name': collector.name,
            'member_count': summary['member_count'],
            'total_savings': _num(summary['total_savings']),
            'total_withdrawals': _num(summary['total_withdrawals']),
            'total_balance': _num(summary['total_balance']),
            'amount_to_be_returned': _num(summary['amount_to_be_returned']),
            'amount_carried_forward': _num(summary['amount_carried_forward']),
        })

    return Response({'cycle_name': cycle.name if cycle else None, 'collectors': rows})