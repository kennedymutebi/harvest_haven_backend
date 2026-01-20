from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone  # ✅ ADDED
from savings.models import SavingsCycle
from savings.serializers import SavingsCycleSerializer, CreateSavingsCycleSerializer


class CycleViewSet(viewsets.ModelViewSet):
    """API for managing savings cycles"""
    
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
    
    def retrieve(self, request, *args, **kwargs):
        """GET /api/cycles/{id}/"""
        cycle = self.get_object()
        serializer = self.get_serializer(cycle)
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
    
    def update(self, request, *args, **kwargs):
        """PUT /api/cycles/{id}/"""
        cycle = self.get_object()
        serializer = self.get_serializer(cycle, data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        
        return Response(SavingsCycleSerializer(cycle).data)
    
    def partial_update(self, request, *args, **kwargs):
        """PATCH /api/cycles/{id}/"""
        cycle = self.get_object()
        serializer = self.get_serializer(cycle, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save()
        
        return Response(SavingsCycleSerializer(cycle).data)
    
    def destroy(self, request, *args, **kwargs):
        """DELETE /api/cycles/{id}/"""
        cycle = self.get_object()
        cycle.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
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
        """POST /api/cycles/{id}/close/ - Close cycle and set end_date"""
        cycle = self.get_object()
        
        if cycle.status != 'active':
            return Response(
                {'detail': 'Only active cycles can be closed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ✅ ADDED: Set end_date to today when closing
        cycle.status = 'closed'
        cycle.end_date = timezone.now().date()  # ✅ New line
        cycle.save()
        
        serializer = self.get_serializer(cycle)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])  # ✅ ADDED entire method
    def reopen(self, request, pk=None):
        """POST /api/cycles/{id}/reopen/ - Reopen a closed cycle"""
        cycle = self.get_object()
        
        if cycle.status != 'closed':
            return Response(
                {'detail': 'Only closed cycles can be reopened'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if there's already an active cycle
        if SavingsCycle.objects.filter(status='active').exists():
            return Response(
                {'detail': 'There is already an active cycle'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reopen cycle and clear end_date
        cycle.status = 'active'
        cycle.end_date = None  # Clear end_date
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