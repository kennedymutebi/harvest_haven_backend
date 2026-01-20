from rest_framework import serializers
from .models import SavingsCycle, SavingsEntry
from authentication.models import MemberProfile


class SavingsCycleSerializer(serializers.ModelSerializer):
    """Serializer for savings cycle"""
    
    total_savings = serializers.SerializerMethodField()
    total_profit = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    
    class Meta:
        model = SavingsCycle
        fields = [
            'id' ,'name', 'start_date', 'end_date', 'status',
            'interest_rate', 'total_savings', 'total_profit',
            'member_count', 'created_at', 'updated_at'
        ]
    
    def get_total_savings(self, obj):
        return float(obj.total_savings())
    
    def get_total_profit(self, obj):
        return float(obj.total_profit())
    
    def get_member_count(self, obj):
        return obj.member_count()


class CreateSavingsCycleSerializer(serializers.Serializer):
    """Serializer for creating cycle"""
    
    start_date = serializers.DateField()
    
    def validate_start_date(self, value):
        # Check if there's already an active cycle
        if SavingsCycle.objects.filter(status='active').exists():
            raise serializers.ValidationError(
                "There is already an active cycle. Close it first."
            )
        return value
    
    def create(self, validated_data):
        start_date = validated_data['start_date']
        
        # Generate name
        name = start_date.strftime("%B %Y")
        
        # ✅ CHANGED: Don't set end_date - it will be None until cycle is closed
        cycle = SavingsCycle.objects.create(
            name=name,
            start_date=start_date,
            end_date=None,  # ✅ Changed from calculating last day of month
            status='active'
        )
        
        return cycle


class SavingsEntrySerializer(serializers.ModelSerializer):
    """Serializer for savings entry"""
    
    member_name = serializers.SerializerMethodField()
    member_id = serializers.CharField(source='member.membership_id', read_only=True)
    cycle_name = serializers.CharField(source='cycle.name', read_only=True)
    
    class Meta:
        model = SavingsEntry
        fields = [
            'id', 'member', 'member_id', 'member_name', 'cycle',
            'cycle_name', 'amount', 'date', 'comment',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_member_name(self, obj):
        return obj.member.user.get_full_name()


class CreateSavingsEntrySerializer(serializers.Serializer):
    """Serializer for creating savings entry"""
    
    member = serializers.PrimaryKeyRelatedField(queryset=MemberProfile.objects.all())
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    date = serializers.DateField()
    comment = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        # Get active cycle
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        if not active_cycle:
            raise serializers.ValidationError("No active savings cycle found")
        
        # ✅ CHANGED: Only validate date is after start_date (no end_date check)
        if data['date'] < active_cycle.start_date:
            raise serializers.ValidationError(
                f"Date must be on or after {active_cycle.start_date}"
            )
        
        data['cycle'] = active_cycle
        return data
    
    def create(self, validated_data):
        return SavingsEntry.objects.create(**validated_data)