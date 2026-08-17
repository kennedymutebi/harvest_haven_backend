from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from savings.models import SavingsCycle
from savings.serializers import SavingsCycleSerializer, CreateSavingsCycleSerializer


class CycleViewSet(viewsets.ModelViewSet):
    """
    Fully free savings cycle API.
    
    - Create any cycle (past, present, future — no restrictions)
    - Multiple active cycles allowed
    - Delete any cycle at any time
    - Close / reopen freely
    
    Endpoints:
        GET    /api/cycles/               → list all cycles
        POST   /api/cycles/               → create new cycle
        GET    /api/cycles/{id}/          → get single cycle
        PUT    /api/cycles/{id}/          → full update
        PATCH  /api/cycles/{id}/          → partial update
        DELETE /api/cycles/{id}/          → delete (no restrictions)
        POST   /api/cycles/{id}/close/    → mark as closed
        POST   /api/cycles/{id}/reopen/   → mark as active
        GET    /api/cycles/active/        → get first active cycle
        GET    /api/cycles/statistics/    → counts by status
    """

    permission_classes = [IsAuthenticated]
    queryset = SavingsCycle.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateSavingsCycleSerializer
        return SavingsCycleSerializer

    # ─── Standard CRUD ───────────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        """GET /api/cycles/ — list all cycles"""
        queryset = self.get_queryset()
        serializer = SavingsCycleSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """GET /api/cycles/{id}/"""
        cycle = self.get_object()
        return Response(SavingsCycleSerializer(cycle).data)

    def create(self, request, *args, **kwargs):
        """
        POST /api/cycles/
        
        Required:  start_date (YYYY-MM-DD)
        Optional:  name, end_date, status, interest_rate
        
        No restrictions — create any cycle you want.
        """
        serializer = CreateSavingsCycleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        return Response(
            SavingsCycleSerializer(cycle).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        """PUT /api/cycles/{id}/"""
        cycle = self.get_object()
        serializer = CreateSavingsCycleSerializer(cycle, data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        return Response(SavingsCycleSerializer(cycle).data)

    def partial_update(self, request, *args, **kwargs):
        """PATCH /api/cycles/{id}/"""
        cycle = self.get_object()
        serializer = CreateSavingsCycleSerializer(cycle, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        return Response(SavingsCycleSerializer(cycle).data)

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /api/cycles/{id}/
        
        Permanently deletes cycle and ALL its savings entries.
        No status restrictions — any cycle can be deleted.
        """
        cycle = self.get_object()
        cycle_name = cycle.name
        cycle.delete()
        return Response(
            {'detail': f'Cycle "{cycle_name}" deleted successfully.'},
            status=status.HTTP_200_OK  # Returns message so frontend knows it worked
        )

    # ─── Custom Actions ───────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def active(self, request):
        """GET /api/cycles/active/ — returns first active cycle"""
        cycle = SavingsCycle.objects.filter(status='active').first()
        if not cycle:
            return Response(
                {'detail': 'No active cycle found'},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(SavingsCycleSerializer(cycle).data)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        POST /api/cycles/{id}/close/
        Sets status='closed' and records today as end_date.
        Works on any cycle regardless of current status.
        """
        cycle = self.get_object()
        cycle.status = 'closed'
        cycle.end_date = timezone.now().date()
        cycle.save()
        return Response(SavingsCycleSerializer(cycle).data)

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        """
        POST /api/cycles/{id}/reopen/
        Sets status='active' and clears end_date.
        No restriction — reopen even if another active cycle exists.
        """
        cycle = self.get_object()
        cycle.status = 'active'
        cycle.end_date = None
        cycle.save()
        return Response(SavingsCycleSerializer(cycle).data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """GET /api/cycles/statistics/"""
        return Response({
            'total': SavingsCycle.objects.count(),
            'active': SavingsCycle.objects.filter(status='active').count(),
            'upcoming': SavingsCycle.objects.filter(status='upcoming').count(),
            'closed': SavingsCycle.objects.filter(status='closed').count(),
        })