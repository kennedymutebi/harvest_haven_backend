from rest_framework import serializers
from authentication.models import User, MemberProfile
import re
import uuid
from django.db import transaction


class MemberListSerializer(serializers.ModelSerializer):
    """For listing members (lightweight)"""
    
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email')
    phone_number = serializers.CharField(source='user.phone_number')
    total_savings = serializers.SerializerMethodField()
    
    class Meta:
        model = MemberProfile
        fields = [
            'id', 'membership_id', 'full_name', 'email', 'phone_number',
            'place_of_residence', 'date_joined', 'total_savings', 'is_active_member'
        ]
    
    def get_full_name(self, obj):
        return obj.user.get_full_name()
    
    def get_total_savings(self, obj):
        from savings.models import SavingsEntry
        from django.db.models import Sum
        total = SavingsEntry.objects.filter(member=obj).aggregate(
            total=Sum('amount')
        )['total']
        return float(total) if total else 0.00


class MemberDetailSerializer(serializers.ModelSerializer):
    """For viewing single member details"""
    
    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    full_name = serializers.SerializerMethodField()
    total_savings = serializers.SerializerMethodField()
    
    class Meta:
        model = MemberProfile
        fields = [
            'id', 'membership_id', 'email', 'first_name', 'last_name',
            'full_name', 'phone_number', 'place_of_residence', 'date_joined',
            'profile_picture', 'is_active_member', 'date_of_birth',
            'national_id', 'emergency_contact_name', 'emergency_contact_phone',
            'total_savings', 'created_at', 'updated_at'
        ]
    
    def get_full_name(self, obj):
        return obj.user.get_full_name()
    
    def get_total_savings(self, obj):
        from savings.models import SavingsEntry
        from django.db.models import Sum
        total = SavingsEntry.objects.filter(member=obj).aggregate(
            total=Sum('amount')
        )['total']
        return float(total) if total else 0.00


class CreateMemberSerializer(serializers.Serializer):
    """For creating new member - Simplified with only essential fields"""
    
    # Required fields
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=20)
    place_of_residence = serializers.CharField(max_length=100)
    
    def validate_first_name(self, value):
        """Validate first name"""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("First name cannot be empty")
        if len(value) < 2:
            raise serializers.ValidationError("First name must be at least 2 characters")
        return value
    
    def validate_last_name(self, value):
        """Validate last name"""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Last name cannot be empty")
        if len(value) < 2:
            raise serializers.ValidationError("Last name must be at least 2 characters")
        return value
    
    def validate_phone_number(self, value):
        """Validate and normalize phone number"""
        # Remove spaces, dashes, parentheses
        cleaned = re.sub(r'[\s\-()]', '', value)
        
        # Normalize to international format
        if cleaned.startswith('0'):
            cleaned = '+256' + cleaned[1:]
        elif not cleaned.startswith('+'):
            cleaned = '+256' + cleaned
        
        # Validate format
        if not re.match(r'^\+256[0-9]{9}$', cleaned):
            raise serializers.ValidationError(
                "Invalid phone number format. Use: 0752682559 or +256752682559"
            )
        
        # Check if phone number already exists
        if User.objects.filter(phone_number=cleaned).exists():
            raise serializers.ValidationError("Phone number already exists")
        
        return cleaned
    
    def validate_place_of_residence(self, value):
        """Validate place of residence"""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Place of residence cannot be empty")
        return value
    
    @transaction.atomic
    def create(self, validated_data):
        """Create user and member profile"""
        try:
            # Generate safe username from names
            first = re.sub(r'[^a-zA-Z0-9]', '', validated_data['first_name'].lower())
            last = re.sub(r'[^a-zA-Z0-9]', '', validated_data['last_name'].lower())
            
            # Limit username length
            base_username = f"{first[:10]}{last[:10]}"
            
            # Make username unique
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
                if counter > 1000:  # Safety limit
                    raise serializers.ValidationError("Could not generate unique username")
            
            # ✅ FIXED: Members don't need email (set to None)
            # Only admins who login need emails
            
            # Create user
            user = User.objects.create(
                username=username,
                email=None,  # ✅ Members don't need email
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                phone_number=validated_data['phone_number'],
                is_admin_approved=True,
                is_active=False  # Members don't login
            )
            
            # Set unusable password
            user.set_unusable_password()
            user.save()
            
            # Create profile
            profile = MemberProfile.objects.create(
                user=user,
                place_of_residence=validated_data['place_of_residence']
            )
            
            return profile
            
        except Exception as e:
            # Log the actual error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error creating member: {str(e)}", exc_info=True)
            raise serializers.ValidationError(f"Failed to create member: {str(e)}")


class UpdateMemberSerializer(serializers.Serializer):
    """For updating member - Simplified"""
    
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    phone_number = serializers.CharField(max_length=20, required=False)
    place_of_residence = serializers.CharField(max_length=100, required=False)
    is_active_member = serializers.BooleanField(required=False)
    
    def validate_first_name(self, value):
        """Validate first name"""
        if value:
            value = value.strip()
            if len(value) < 2:
                raise serializers.ValidationError("First name must be at least 2 characters")
        return value
    
    def validate_last_name(self, value):
        """Validate last name"""
        if value:
            value = value.strip()
            if len(value) < 2:
                raise serializers.ValidationError("Last name must be at least 2 characters")
        return value
    
    def validate_phone_number(self, value):
        """Validate and normalize phone number"""
        if not value:
            return value
        
        # Remove spaces, dashes, parentheses
        cleaned = re.sub(r'[\s\-()]', '', value)
        
        # Normalize to international format
        if cleaned.startswith('0'):
            cleaned = '+256' + cleaned[1:]
        elif not cleaned.startswith('+'):
            cleaned = '+256' + cleaned
        
        # Validate format
        if not re.match(r'^\+256[0-9]{9}$', cleaned):
            raise serializers.ValidationError(
                "Invalid phone number format. Use: 0752682559 or +256752682559"
            )
        
        # Check if phone number already exists (excluding current user)
        instance = self.instance
        if instance and User.objects.filter(phone_number=cleaned).exclude(id=instance.user.id).exists():
            raise serializers.ValidationError("Phone number already exists")
        
        return cleaned
    
    def validate_place_of_residence(self, value):
        """Validate place of residence"""
        if value:
            value = value.strip()
            if not value:
                raise serializers.ValidationError("Place of residence cannot be empty")
        return value
    
    @transaction.atomic
    def update(self, instance, validated_data):
        """Update user and profile"""
        try:
            # Update user fields
            if 'first_name' in validated_data:
                instance.user.first_name = validated_data['first_name']
            if 'last_name' in validated_data:
                instance.user.last_name = validated_data['last_name']
            if 'phone_number' in validated_data:
                instance.user.phone_number = validated_data['phone_number']
            
            instance.user.save()
            
            # Update profile fields
            if 'place_of_residence' in validated_data:
                instance.place_of_residence = validated_data['place_of_residence']
            if 'is_active_member' in validated_data:
                instance.is_active_member = validated_data['is_active_member']
            
            instance.save()
            
            return instance
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error updating member: {str(e)}", exc_info=True)
            raise serializers.ValidationError(f"Failed to update member: {str(e)}")