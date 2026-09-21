from decimal import Decimal

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from savings.models import SavingsCycle
from savings.serializers import SavingsCycleSerializer, CreateSavingsCycleSerializer
from savings.reporting import get_cycle_summary_for_all_members
from savings.infrastructure import get_cycle_total_profit
from authentication.models import MemberProfile


class CycleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = SavingsCycle.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateSavingsCycleSerializer
        return SavingsCycleSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = SavingsCycleSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        cycle = self.get_object()
        return Response(SavingsCycleSerializer(cycle).data)

    def create(self, request, *args, **kwargs):
        serializer = CreateSavingsCycleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        return Response(SavingsCycleSerializer(cycle).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        cycle = self.get_object()
        serializer = CreateSavingsCycleSerializer(cycle, data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        return Response(SavingsCycleSerializer(cycle).data)

    def partial_update(self, request, *args, **kwargs):
        cycle = self.get_object()
        serializer = CreateSavingsCycleSerializer(cycle, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        return Response(SavingsCycleSerializer(cycle).data)

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /api/cycles/{id}/

        FIXED: previously deleted the cycle AND cascaded to every savings
        entry / withdrawal in it, unconditionally. Per the spec ("nothing
        is ever deleted once money has moved") and per your own intent
        ("not deleting information, just keep tracking the current
        month"), a cycle that has any recorded activity can no longer be
        deleted — only an empty (e.g. mistakenly created upcoming) cycle
        can.
        """
        cycle = self.get_object()

        if cycle.savings_entries.exists() or cycle.withdrawals.exists():
            return Response(
                {
                    'error': (
                        f'"{cycle.name}" has savings or withdrawals recorded '
                        'and cannot be deleted. Correct individual entries '
                        'instead of deleting the cycle.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        cycle_name = cycle.name
        cycle.delete()
        return Response(
            {'detail': f'Cycle "{cycle_name}" deleted successfully.'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def active(self, request):
        cycle = SavingsCycle.objects.filter(status='active').first()
        if not cycle:
            return Response({'detail': 'No active cycle found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(SavingsCycleSerializer(cycle).data)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        cycle = self.get_object()
        if cycle.status != 'active':
            return Response({'detail': 'Only active cycles can be closed'}, status=status.HTTP_400_BAD_REQUEST)
        cycle.status = 'closed'
        cycle.end_date = timezone.now().date()
        cycle.save()
        return Response(SavingsCycleSerializer(cycle).data)

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        cycle = self.get_object()
        cycle.status = 'active'
        cycle.end_date = None
        cycle.save()
        return Response(SavingsCycleSerializer(cycle).data)

    @action(detail=True, methods=['get'])
    def close_preview(self, request, pk=None):
        """
        GET /api/cycles/{id}/close_preview/

        NEW. Whole-cycle summary shown to the admin before confirming
        close: combined opening balance (B/F across all members),
        this cycle's saved/withdrawn, the resulting closing balance, and
        the total Section-7 fee — computed live, nothing stored.
        """
        cycle = self.get_object()
        if cycle.status != 'active':
            return Response(
                {'detail': 'Only an active cycle can be previewed for closing'},
                status=status.HTTP_400_BAD_REQUEST
            )

        members = MemberProfile.objects.filter(is_active_member=True)
        rows = get_cycle_summary_for_all_members(cycle, members)

        opening_balance = sum((r['opening_balance'] for r in rows), Decimal('0.00'))
        total_saved = sum((r['savings'] for r in rows), Decimal('0.00'))
        total_withdrawn = sum((r['withdrawals'] for r in rows), Decimal('0.00'))
        closing_balance = sum((r['closing_balance'] for r in rows), Decimal('0.00'))
        total_fees = get_cycle_total_profit(cycle)

        return Response({
            'cycle': {'id': cycle.id, 'name': cycle.name},
            'opening_balance': float(opening_balance),
            'total_saved': float(total_saved),
            'total_withdrawn': float(total_withdrawn),
            'closing_balance': float(closing_balance),
            'total_fees': float(total_fees),
            'members_count': len(rows),
        })

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        return Response({
            'total': SavingsCycle.objects.count(),
            'active': SavingsCycle.objects.filter(status='active').count(),
            'upcoming': SavingsCycle.objects.filter(status='upcoming').count(),
            'closed': SavingsCycle.objects.filter(status='closed').count(),
        })