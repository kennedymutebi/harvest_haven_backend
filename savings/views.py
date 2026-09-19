from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q
from django.http import HttpResponse
from django.core.cache import cache
from .models import SavingsCycle, SavingsEntry, Withdrawal
from authentication.models import MemberProfile, Collector
from .serializers import (
    SavingsCycleSerializer, CreateSavingsCycleSerializer,
    SavingsEntrySerializer, CreateSavingsEntrySerializer,
    WithdrawalSerializer, CreateWithdrawalSerializer
)
from .reporting import get_member_cycle_summary, get_member_lifetime_history
from .exports import (
    build_cycle_export,
    build_member_history_export,
    build_collector_export,
    build_all_collectors_export,
)
from .sms_service import SMSService
from .pdf_exports import (
    build_cycle_pdf,
    build_member_statement_pdf,
    build_collector_pdf,
)
import logging

logger = logging.getLogger(__name__)


# ============================================
# SAVINGS ENTRIES
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

        member_id = request.query_params.get('member')
        if member_id:
            queryset = queryset.filter(member_id=member_id)

        cycle_id = request.query_params.get('cycle')
        if cycle_id:
            queryset = queryset.filter(cycle_id=cycle_id)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        POST /api/savings/

        Normal deposit: no `cycle` in body -> goes to the active cycle.
        Late-save: include `cycle` (any cycle id, usually a closed one) ->
        backdated into that cycle, permanently, without touching the
        active cycle's totals.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(created_by=request.user)

        # Invalidate cached members/savings lists so new deposits show up
        # immediately instead of waiting for the cache TTL to expire.
        try:
            cache.delete_pattern("*members_savings_*")
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {str(e)}")

        send_sms = str(request.data.get('send_sms', 'false')).lower() == 'true'
        if send_sms:
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
        else:
            logger.info(f"SMS skipped for savings entry {entry.id} (send_sms=false)")

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

        # Invalidate cache on update too — amount may have changed.
        try:
            cache.delete_pattern("*members_savings_*")
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {str(e)}")

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
        """
        DELETE /api/savings/{id}/

        GUARD: if a withdrawal has already drawn from this deposit
        (i.e. it has WithdrawalAllocation rows), deleting it would corrupt
        that withdrawal's FIFO trail — so this is blocked.
        """
        entry = self.get_object()
        if entry.is_withdrawn_from:
            return Response(
                {
                    'error': (
                        'This entry cannot be deleted because a withdrawal has '
                        'already drawn money from it. Deleting it would break '
                        'that withdrawal\'s record.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        entry.delete()

        # Invalidate cache on delete too.
        try:
            cache.delete_pattern("*members_savings_*")
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {str(e)}")

        return Response(status=status.HTTP_204_NO_CONTENT)


class LateSavingsEntryView(APIView):
    """
    POST /api/savings/late-entry/

    Backdate a saving into a specific past/closed cycle. Excluded from the
    active cycle's totals entirely, since cycle scoping already does that.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateSavingsEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data['cycle'].status == 'active':
            return Response(
                {'error': 'Use the normal savings entry endpoint for the active cycle.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        entry = serializer.save(created_by=request.user)

        try:
            cache.delete_pattern("*members_savings_*")
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {str(e)}")

        return Response(SavingsEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class MemberSearchView(APIView):
    """GET /api/members/search/?q=<name, membership id, or phone>"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.GET.get('q', '').strip()
        members = MemberProfile.objects.select_related('user', 'collector').all()

        if query:
            members = members.filter(
                Q(user__first_name__icontains=query) |
                Q(user__last_name__icontains=query) |
                Q(membership_id__icontains=query) |
                Q(user__phone_number__icontains=query)
            )

        members = members[:25]

        results = [{
            'id': m.id,
            'name': m.user.get_full_name(),
            'membership_id': m.membership_id,
            'collector': m.collector.name if m.collector else None,
            'is_active_member': m.is_active_member,
        } for m in members]

        return Response({'results': results, 'count': len(results)})


# ============================================
# COLLECTOR SUMMARY
# ============================================

class CollectorSavingsSummaryView(APIView):
    """
    GET /api/savings/collectors/{collector_id}/summary/?date=YYYY-MM-DD
    GET /api/savings/collectors/{collector_id}/summary/?month=YYYY-MM
    GET /api/savings/collectors/{collector_id}/summary/?cycle=<cycle_id>
    GET /api/savings/collectors/{collector_id}/summary/   (all-time)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, collector_id):
        try:
            collector = Collector.objects.get(id=collector_id)
        except Collector.DoesNotExist:
            return Response({'error': 'Collector not found'}, status=status.HTTP_404_NOT_FOUND)

        members = MemberProfile.objects.filter(collector=collector)

        entries = SavingsEntry.objects.filter(member__in=members)
        withdrawals = Withdrawal.objects.filter(member__in=members)

        date_str = request.query_params.get('date')
        month_str = request.query_params.get('month')
        cycle_id = request.query_params.get('cycle')

        if cycle_id:
            entries = entries.filter(cycle_id=cycle_id)
            withdrawals = withdrawals.filter(cycle_id=cycle_id)
            period_label = f'cycle:{cycle_id}'
        elif date_str:
            entries = entries.filter(date=date_str)
            withdrawals = withdrawals.filter(date=date_str)
            period_label = date_str
        elif month_str:
            try:
                year, month = month_str.split('-')
                entries = entries.filter(date__year=year, date__month=month)
                withdrawals = withdrawals.filter(date__year=year, date__month=month)
            except ValueError:
                return Response(
                    {'error': 'month must be in YYYY-MM format'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            period_label = month_str
        else:
            period_label = 'all-time'

        total_saved = entries.aggregate(total=Sum('amount'))['total'] or 0
        total_withdrawn = withdrawals.aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'collector': {'id': collector.id, 'name': collector.name},
            'period': period_label,
            'total_saved': float(total_saved),
            'total_withdrawn': float(total_withdrawn),
            'net_balance': float(total_saved) - float(total_withdrawn),
            'members_count': members.count(),
            'entries_count': entries.count(),
        })


# ============================================
# CYCLES
# ============================================

class SavingsCycleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing savings cycles"""

    permission_classes = [IsAuthenticated]
    queryset = SavingsCycle.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateSavingsCycleSerializer
        return SavingsCycleSerializer

    def list(self, request, *args, **kwargs):
        """GET /api/cycles/?status=closed"""
        queryset = self.get_queryset()
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
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
# WITHDRAWALS
# ============================================

class WithdrawalViewSet(viewsets.ModelViewSet):
    """API for managing withdrawals — see CreateWithdrawalSerializer for the
    cycle-scoping fix that keeps a new cycle's balance clean."""

    permission_classes = [IsAuthenticated]
    queryset = Withdrawal.objects.select_related('member', 'cycle', 'created_by').prefetch_related('allocations').all()

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateWithdrawalSerializer
        return WithdrawalSerializer

    def list(self, request, *args, **kwargs):
        """GET /api/savings/withdrawals/"""
        queryset = self.get_queryset()

        member_id = request.query_params.get('member')
        if member_id:
            queryset = queryset.filter(member_id=member_id)

        cycle_id = request.query_params.get('cycle')
        if cycle_id:
            queryset = queryset.filter(cycle_id=cycle_id)

        serializer = WithdrawalSerializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """POST /api/savings/withdrawals/"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        withdrawal = serializer.save(created_by=request.user)

        try:
            cache.delete_pattern("*members_savings_*")
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {str(e)}")

        return Response(
            WithdrawalSerializer(withdrawal).data,
            status=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        """GET /api/savings/withdrawals/{id}/"""
        withdrawal = self.get_object()
        return Response(WithdrawalSerializer(withdrawal).data)


# ============================================
# VIEWS FOR "VIEW SAVINGS" PAGE
# ============================================

class MembersListWithSavingsView(APIView):
    """
    GET /api/view-savings/members/

    PERFORMANCE NOTE: this used to run 2 DB queries PER MEMBER inside a
    Python loop (N+1 problem) — with a few hundred members that meant
    600+ queries and 20-30+ second load times. Now it runs 2 queries
    TOTAL regardless of member count, using annotate+Sum grouped by
    member_id, plus a short Redis cache on top for repeat requests.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        search_query = request.GET.get('search', '').strip()
        show_all = request.GET.get('all', '').lower() == 'true'

        # Cache key is scoped per-user + filters so nobody sees another
        # user's filtered/restricted view from cache.
        cache_key = f"members_savings_{request.user.id}_{search_query}_{show_all}"
        try:
            cached = cache.get(cache_key)
        except Exception as e:
            logger.warning(f"Cache read failed: {str(e)}")
            cached = None
        if cached is not None:
            return Response(cached)

        active_cycle = SavingsCycle.objects.filter(status='active').first()

        if not active_cycle:
            data = {
                'members': [],
                'total_count': 0,
                'cycle_name': None,
                'error': 'No active cycle found'
            }
            return Response(data)

        # select_related('user') avoids a separate query per member for
        # member.user.first_name / last_name.
        members = MemberProfile.objects.filter(is_active_member=True).select_related('user')

        if not (show_all and (request.user.is_staff or request.user.is_superuser)):
            members = members.filter(registered_by=request.user)

        if search_query:
            members = members.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(membership_id__icontains=search_query)
            )

        members = list(members)  # evaluate once, reuse below
        member_ids = [m.id for m in members]

        # ONE query: total savings for ALL members, grouped by member_id.
        savings_map = dict(
            SavingsEntry.objects.filter(member_id__in=member_ids, cycle=active_cycle)
            .values('member_id')
            .annotate(total=Sum('amount'))
            .values_list('member_id', 'total')
        )

        # ONE query: total withdrawals for ALL members, grouped by member_id.
        withdrawn_map = dict(
            Withdrawal.objects.filter(member_id__in=member_ids, cycle=active_cycle)
            .values('member_id')
            .annotate(total=Sum('amount'))
            .values_list('member_id', 'total')
        )

        result = []
        for member in members:
            total_savings = float(savings_map.get(member.id, 0) or 0)
            total_withdrawn = float(withdrawn_map.get(member.id, 0) or 0)

            result.append({
                'id': member.id,
                'name': f"{member.user.first_name} {member.user.last_name}",
                'first_name': member.user.first_name,
                'last_name': member.user.last_name,
                'membership_id': member.membership_id,
                'total_savings': total_savings,
                'total_withdrawn': total_withdrawn,
                'balance': total_savings - total_withdrawn,
                'initials': f"{member.user.first_name[0]}{member.user.last_name[0]}".upper() if member.user.first_name and member.user.last_name else "??"
            })

        result.sort(key=lambda x: x['total_savings'], reverse=True)

        data = {
            'members': result,
            'total_count': len(result),
            'cycle_name': active_cycle.name
        }

        # 60s TTL — short enough that stale balances aren't a real problem,
        # and we invalidate immediately on any create/update/delete anyway.
        cache.set(cache_key, data, timeout=60)

        return Response(data)


class MemberSavingsDetailView(APIView):
    """GET /api/view-savings/members/{member_id}/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):
        try:
            member = MemberProfile.objects.select_related('user').get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)

        active_cycle = SavingsCycle.objects.filter(status='active').first()
        if not active_cycle:
            return Response({'error': 'No active cycle found'}, status=status.HTTP_404_NOT_FOUND)

        summary = get_member_cycle_summary(member, active_cycle)

        entries = SavingsEntry.objects.filter(
            member=member, cycle=active_cycle
        ).order_by('-date', '-created_at')

        total_lifetime = SavingsEntry.objects.filter(
            member=member
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_withdrawn_lifetime = Withdrawal.objects.filter(
            member=member
        ).aggregate(total=Sum('amount'))['total'] or 0

        entries_list = [{
            'id': entry.id,
            'date': entry.date.strftime('%b %d, %Y'),
            'amount': float(entry.amount),
            'withdrawn_amount': float(entry.withdrawn_amount),
            'remaining_amount': float(entry.remaining_amount),
            'comment': entry.comment or ''
        } for entry in entries]

        withdrawals_list = [{
            'id': w.id,
            'date': w.date.strftime('%b %d, %Y'),
            'amount': float(w.amount),
            'reason': w.reason
        } for w in Withdrawal.objects.filter(member=member, cycle=active_cycle).order_by('-date', '-created_at')]

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
                'month': active_cycle.start_date.strftime('%B %Y')
            },
            'total_lifetime': float(total_lifetime),
            'total_withdrawn_lifetime': float(total_withdrawn_lifetime),
            'net_balance_lifetime': float(total_lifetime) - float(total_withdrawn_lifetime),

            # ✅ Frontend (WithdrawPage.tsx) reads this exact field name.
            # Points at the ACTIVE CYCLE's balance — the same number the
            # withdrawal endpoint validates against.
            'net_balance': float(summary['closing_balance']),

            'total_this_month': float(summary['savings']),
            'total_withdrawn_this_month': float(summary['withdrawals']),
            'balance_this_month': float(summary['closing_balance']),
            'carry_forward': float(summary['carry_forward']),

            'entries_count': entries.count(),
            'entries': entries_list,
            'withdrawals': withdrawals_list
        })


class MemberSavingsHistoryView(APIView):
    """GET /api/view-savings/members/{member_id}/history/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):
        try:
            member = MemberProfile.objects.select_related('user').get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)

        summaries = get_member_lifetime_history(member)

        history = [{
            'cycle_id': s['cycle'].id,
            'cycle_name': s['cycle'].name,
            'start_date': s['cycle'].start_date.isoformat(),
            'end_date': s['cycle'].end_date.isoformat() if s['cycle'].end_date else None,
            'status': s['cycle'].status,
            'opening_balance': float(s['opening_balance']),
            'carry_forward': float(s['carry_forward']),
            'total_saved': float(s['savings']),
            'total_withdrawn': float(s['withdrawals']),
            'returned_amount': float(s['returned_amount']),
            'closing_balance': float(s['closing_balance']),
        } for s in summaries]

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
            'total_cycles': len(history),
            'history': history
        })


# ============================================
# EXCEL EXPORTS  (Phase 2 — matches savings/exports.py exactly)
# ============================================

def _xlsx_response(buf, filename):
    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


class CycleExportView(APIView):
    """
    GET /api/savings/export/cycle/?cycle_id=<id>

    Covers both "all members" (no cycle_id -> active cycle) and
    "selected cycle/month" (cycle_id given) — same report, different cycle.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cycle_id = request.query_params.get('cycle_id')
        if cycle_id:
            try:
                cycle = SavingsCycle.objects.get(id=cycle_id)
            except SavingsCycle.DoesNotExist:
                return Response({'error': 'Cycle not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            cycle = SavingsCycle.objects.filter(status='active').first()
            if not cycle:
                return Response({'error': 'No active cycle found'}, status=status.HTTP_404_NOT_FOUND)

        # build_cycle_export queries members itself if none passed, but we
        # can scope it explicitly here to active members only.
        members = MemberProfile.objects.filter(is_active_member=True).select_related('user')
        buf = build_cycle_export(cycle, members)
        filename = f"{cycle.name.replace(' ', '_')}_savings.xlsx"
        return _xlsx_response(buf, filename)


class MemberHistoryExportView(APIView):
    """GET /api/savings/export/member/<member_id>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):
        try:
            member = MemberProfile.objects.select_related('user').get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)

        buf = build_member_history_export(member)
        filename = f"{member.membership_id}_history.xlsx"
        return _xlsx_response(buf, filename)


class CollectorExportView(APIView):
    """GET /api/savings/export/collector/<collector_id>/?cycle_id=<id>"""

    permission_classes = [IsAuthenticated]

    def get(self, request, collector_id):
        try:
            collector = Collector.objects.get(id=collector_id)
        except Collector.DoesNotExist:
            return Response({'error': 'Collector not found'}, status=status.HTTP_404_NOT_FOUND)

        cycle = None
        cycle_id = request.query_params.get('cycle_id')
        if cycle_id:
            try:
                cycle = SavingsCycle.objects.get(id=cycle_id)
            except SavingsCycle.DoesNotExist:
                return Response({'error': 'Cycle not found'}, status=status.HTTP_404_NOT_FOUND)

        members = MemberProfile.objects.filter(collector=collector)
        buf = build_collector_export(collector, members, cycle=cycle)
        filename = f"{collector.name.replace(' ', '_')}_summary.xlsx"
        return _xlsx_response(buf, filename)


class AllCollectorsExportView(APIView):
    """GET /api/savings/export/collectors/?cycle_id=<id>"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cycle = None
        cycle_id = request.query_params.get('cycle_id')
        if cycle_id:
            try:
                cycle = SavingsCycle.objects.get(id=cycle_id)
            except SavingsCycle.DoesNotExist:
                return Response({'error': 'Cycle not found'}, status=status.HTTP_404_NOT_FOUND)

        collectors_with_members = [
            (collector, MemberProfile.objects.filter(collector=collector))
            for collector in Collector.objects.all()
        ]
        buf = build_all_collectors_export(collectors_with_members, cycle=cycle)
        return _xlsx_response(buf, 'all_collectors_summary.xlsx')


# ============================================
# PDF EXPORTS
# ============================================

def _pdf_response(buf, filename):
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


class CyclePdfExportView(APIView):
    """GET /api/savings/export/cycle/pdf/?cycle_id=<id>"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cycle_id = request.query_params.get('cycle_id')
        if cycle_id:
            try:
                cycle = SavingsCycle.objects.get(id=cycle_id)
            except SavingsCycle.DoesNotExist:
                return Response({'error': 'Cycle not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            cycle = SavingsCycle.objects.filter(status='active').first()
            if not cycle:
                return Response({'error': 'No active cycle found'}, status=status.HTTP_404_NOT_FOUND)

        members = MemberProfile.objects.filter(is_active_member=True).select_related('user')
        buf = build_cycle_pdf(cycle, members)
        filename = f"{cycle.name.replace(' ', '_')}_savings.pdf"
        return _pdf_response(buf, filename)


class MemberStatementPdfExportView(APIView):
    """GET /api/savings/export/member/<member_id>/pdf/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):
        try:
            member = MemberProfile.objects.select_related('user').get(id=member_id)
        except MemberProfile.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)

        buf = build_member_statement_pdf(member)
        filename = f"{member.membership_id}_statement.pdf"
        return _pdf_response(buf, filename)


class CollectorPdfExportView(APIView):
    """GET /api/savings/export/collector/<collector_id>/pdf/?cycle_id=<id>"""

    permission_classes = [IsAuthenticated]

    def get(self, request, collector_id):
        try:
            collector = Collector.objects.get(id=collector_id)
        except Collector.DoesNotExist:
            return Response({'error': 'Collector not found'}, status=status.HTTP_404_NOT_FOUND)

        cycle = None
        cycle_id = request.query_params.get('cycle_id')
        if cycle_id:
            try:
                cycle = SavingsCycle.objects.get(id=cycle_id)
            except SavingsCycle.DoesNotExist:
                return Response({'error': 'Cycle not found'}, status=status.HTTP_404_NOT_FOUND)

        members = MemberProfile.objects.filter(collector=collector)
        buf = build_collector_pdf(collector, members, cycle=cycle)
        filename = f"{collector.name.replace(' ', '_')}_summary.pdf"
        return _pdf_response(buf, filename)