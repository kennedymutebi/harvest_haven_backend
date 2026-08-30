from rest_framework import serializers
from authentication.models import User, MemberProfile, Collector
import re
import uuid
from django.db import transaction


class MemberListSerializer(serializers.ModelSerializer):
    """For listing members (lightweight)

    ✅ FIX: total_savings / current_balance previously summed EVERY
    SavingsEntry the member ever made, across every cycle, with no cycle
    filter at all — a completely different (and disagreeing) definition
    of "balance" than the rest of the system uses. This now calls the
    same reporting.get_member_cycle_summary() the savings app uses,
    scoped to the CURRENT ACTIVE CYCLE, so this screen always matches
    what you see in view-savings and in every export.
    """

    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email')
    phone_number = serializers.CharField(source='user.phone_number')
    total_savings = serializers.SerializerMethodField()
    total_withdrawn = serializers.SerializerMethodField()
    current_balance = serializers.SerializerMethodField()
    collector_id = serializers.IntegerField(source='collector.id', read_only=True, default=None)
    collector_name = serializers.SerializerMethodField()

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'membership_id', 'full_name', 'email', 'phone_number',
            'place_of_residence', 'date_joined', 'total_savings',
            'total_withdrawn', 'current_balance',
            'is_active_member', 'registered_by', 'collector_id', 'collector_name'
        ]

    def get_collector_name(self, obj):
        return obj.collector.name if obj.collector else None

    def get_full_name(self, obj):
        return obj.user.get_full_name()

    def _active_cycle_summary(self, obj):
        # Cached per-request via context so we don't hit the DB for the
        # active cycle once per member row when serializing a list.
        active_cycle = self.context.get('_active_cycle')
        if active_cycle is None:
            from savings.models import SavingsCycle
            active_cycle = SavingsCycle.objects.filter(status='active').first()
            self.context['_active_cycle'] = active_cycle or False

        if not active_cycle:
            from decimal import Decimal
            return {'savings': Decimal('0.00'), 'withdrawals': Decimal('0.00'), 'closing_balance': Decimal('0.00')}

        from savings.reporting import get_member_cycle_summary
        return get_member_cycle_summary(obj, active_cycle)

    def get_total_savings(self, obj):
        return float(self._active_cycle_summary(obj)['savings'])

    def get_total_withdrawn(self, obj):
        return float(self._active_cycle_summary(obj)['withdrawals'])

    def get_current_balance(self, obj):
        return float(self._active_cycle_summary(obj)['closing_balance'])


class MemberDetailSerializer(serializers.ModelSerializer):
    """For viewing single member details

    ✅ FIX: same as MemberListSerializer above — current_balance and
    total_savings are now the ACTIVE CYCLE'S numbers (what's actually
    available to withdraw right now), matching every other screen.
    total_savings_lifetime / total_withdrawn_lifetime are added
    separately for anyone who explicitly wants the all-time figures.
    """

    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    full_name = serializers.SerializerMethodField()

    total_savings = serializers.SerializerMethodField()
    total_withdrawn = serializers.SerializerMethodField()
    current_balance = serializers.SerializerMethodField()

    total_savings_lifetime = serializers.SerializerMethodField()
    total_withdrawn_lifetime = serializers.SerializerMethodField()

    registered_by_name = serializers.SerializerMethodField()
    collector_id = serializers.IntegerField(source='collector.id', read_only=True, default=None)
    collector_name = serializers.SerializerMethodField()

    def get_collector_name(self, obj):
        return obj.collector.name if obj.collector else None

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'membership_id', 'email', 'first_name', 'last_name',
            'full_name', 'phone_number', 'place_of_residence', 'date_joined',
            'profile_picture', 'is_active_member', 'date_of_birth',
            'national_id', 'emergency_contact_name', 'emergency_contact_phone',
            'total_savings', 'current_balance', 'total_withdrawn',
            'total_savings_lifetime', 'total_withdrawn_lifetime',
            'registered_by', 'registered_by_name', 'collector_id', 'collector_name',
            'created_at', 'updated_at'
        ]

    def get_full_name(self, obj):
        return obj.user.get_full_name()

    def _active_cycle_summary(self, obj):
        from savings.models import SavingsCycle
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        if not active_cycle:
            from decimal import Decimal
            return {'savings': Decimal('0.00'), 'withdrawals': Decimal('0.00'), 'closing_balance': Decimal('0.00')}

        from savings.reporting import get_member_cycle_summary
        return get_member_cycle_summary(obj, active_cycle)

    def get_total_savings(self, obj):
        return float(self._active_cycle_summary(obj)['savings'])

    def get_total_withdrawn(self, obj):
        return float(self._active_cycle_summary(obj)['withdrawals'])

    def get_current_balance(self, obj):
        return float(self._active_cycle_summary(obj)['closing_balance'])

    def get_total_savings_lifetime(self, obj):
        from savings.models import SavingsEntry
        from django.db.models import Sum
        total = SavingsEntry.objects.filter(member=obj).aggregate(total=Sum('amount'))['total']
        return float(total) if total else 0.00

    def get_total_withdrawn_lifetime(self, obj):
        from savings.models import Withdrawal
        from django.db.models import Sum
        total = Withdrawal.objects.filter(member=obj).aggregate(total=Sum('amount'))['total']
        return float(total) if total else 0.00

    def get_registered_by_name(self, obj):
        return obj.registered_by.get_full_name() if obj.registered_by else None


class CreateMemberSerializer(serializers.Serializer):
    """For creating new member - Simplified with only essential fields"""

    # Required fields
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    # ✅ Optional now — a member can be registered with just a name
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    place_of_residence = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Dropdown — which Collector this member belongs to
    collector = serializers.PrimaryKeyRelatedField(
        queryset=Collector.objects.filter(is_active=True),
        required=True,
        error_messages={'required': 'Please select which collector this member belongs to.'}
    )

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
        """Validate and normalize phone number (optional — skip if blank)"""
        if not value or not value.strip():
            return None  # stored as NULL, not an empty string, so uniqueness still works

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
        """Place of residence is optional — normalize blank to None"""
        if value is None:
            return None
        value = value.strip()
        return value or None

    @transaction.atomic
    def create(self, validated_data):
        """Create user and member profile, attached to the chosen collector"""
        try:
            # Generate safe username from names
            first = re.sub(r'[^a-zA-Z0-9]', '', validated_data['first_name'].lower())
            last = re.sub(r'[^a-zA-Z0-9]', '', validated_data['last_name'].lower())

            # Limit username length
            base_username = f"{first[:10]}{last[:10]}" or "member"

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
                phone_number=validated_data.get('phone_number') or None,
                is_admin_approved=True,
                is_active=False  # Members don't login
            )

            # Set unusable password
            user.set_unusable_password()
            user.save()

            # registered_by tracks which admin account created this record
            request = self.context.get('request')
            registered_by = request.user if request and request.user.is_authenticated else None

            # Create profile, attached to the chosen collector
            profile = MemberProfile.objects.create(
                user=user,
                place_of_residence=validated_data.get('place_of_residence') or None,
                registered_by=registered_by,
                collector=validated_data['collector']
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
        """Validate and normalize phone number (optional)"""
        if not value or not value.strip():
            return None

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
        """Place of residence is optional"""
        if value is None:
            return None
        return value.strip() or None

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