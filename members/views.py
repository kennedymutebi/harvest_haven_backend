from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.db import transaction
from authentication.models import MemberProfile
from .serializers import (
    MemberListSerializer, MemberDetailSerializer,
    CreateMemberSerializer, UpdateMemberSerializer
)
import logging

logger = logging.getLogger(__name__)


class MemberViewSet(viewsets.ModelViewSet):
    """API for managing members"""
    
    permission_classes = [IsAuthenticated]
    queryset = MemberProfile.objects.select_related('user').all()
    
    def get_serializer_class(self):
        if self.action == 'list':
            return MemberListSerializer
        elif self.action == 'create':
            return CreateMemberSerializer
        elif self.action in ['update', 'partial_update']:
            return UpdateMemberSerializer
        return MemberDetailSerializer
    
    def list(self, request, *args, **kwargs):
        """GET /api/members/"""
        try:
            queryset = self.get_queryset()
            
            # Search by name, email, membership_id
            search = request.query_params.get('search', '')
            if search:
                queryset = queryset.filter(
                    Q(membership_id__icontains=search) |
                    Q(user__first_name__icontains=search) |
                    Q(user__last_name__icontains=search) |
                    Q(user__email__icontains=search) |
                    Q(user__phone_number__icontains=search)
                )
            
            serializer = self.get_serializer(queryset, many=True)
            return Response({
                'count': queryset.count(),
                'results': serializer.data
            })
        except Exception as e:
            logger.error(f"Error listing members: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to fetch members: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def retrieve(self, request, pk=None, *args, **kwargs):
        """GET /api/members/{id}/"""
        try:
            member = self.get_object()
            serializer = self.get_serializer(member)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error retrieving member {pk}: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to retrieve member: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """POST /api/members/"""
        try:
            logger.info(f"Creating member with data: {request.data}")
            
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            profile = serializer.save()
            
            logger.info(f"Member created successfully: {profile.membership_id}")
            
            # Send welcome SMS (non-blocking)
            try:
                from savings.sms_service import SMSService
                success, message = SMSService.send_welcome_sms(profile)
                
                if success:
                    logger.info(f"Welcome SMS sent to member {profile.membership_id}")
                else:
                    logger.warning(f"Welcome SMS failed for {profile.membership_id}: {message}")
            
            except ImportError:
                logger.warning("SMS service not available - skipping welcome SMS")
            except Exception as sms_error:
                # Don't fail member creation if SMS fails
                logger.error(f"Welcome SMS exception: {str(sms_error)}")
            
            return Response(
                MemberDetailSerializer(profile).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Error creating member: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to create member: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def update(self, request, pk=None, *args, **kwargs):
        """PUT /api/members/{id}/"""
        try:
            logger.info(f"Updating member {pk} with data: {request.data}")
            
            member = self.get_object()
            serializer = self.get_serializer(member, data=request.data)
            serializer.is_valid(raise_exception=True)
            profile = serializer.save()
            
            logger.info(f"Member {pk} updated successfully")
            
            return Response(MemberDetailSerializer(profile).data)
            
        except Exception as e:
            logger.error(f"Error updating member {pk}: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to update member: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def partial_update(self, request, pk=None, *args, **kwargs):
        """PATCH /api/members/{id}/"""
        try:
            logger.info(f"Partially updating member {pk} with data: {request.data}")
            
            member = self.get_object()
            serializer = self.get_serializer(member, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            profile = serializer.save()
            
            logger.info(f"Member {pk} partially updated successfully")
            
            return Response(MemberDetailSerializer(profile).data)
            
        except Exception as e:
            logger.error(f"Error partially updating member {pk}: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to update member: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def destroy(self, request, pk=None, *args, **kwargs):
        """DELETE /api/members/{id}/"""
        try:
            logger.info(f"Deleting member {pk}")
            
            member = self.get_object()
            user = member.user
            
            # Delete profile and user
            member.delete()
            user.delete()
            
            logger.info(f"Member {pk} deleted successfully")
            
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        except Exception as e:
            logger.error(f"Error deleting member {pk}: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to delete member: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def savings(self, request, pk=None):
        """GET /api/members/{id}/savings/"""
        try:
            member = self.get_object()
            from savings.models import SavingsEntry
            from savings.serializers import SavingsEntrySerializer
            
            entries = SavingsEntry.objects.filter(member=member).order_by('-date')
            
            # Filter by cycle
            cycle_id = request.query_params.get('cycle')
            if cycle_id:
                entries = entries.filter(cycle_id=cycle_id)
            
            serializer = SavingsEntrySerializer(entries, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Error fetching savings for member {pk}: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to fetch savings: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )