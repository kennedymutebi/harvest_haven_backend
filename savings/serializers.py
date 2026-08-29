from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F
from rest_framework import serializers
from .models import SavingsCycle, SavingsEntry, Withdrawal, WithdrawalAllocation
from authentication.models import MemberProfile


class SavingsCycleSerializer(serializers.ModelSerializer):
    """Full read serializer with computed fields"""

    total_savings = serializers.SerializerMethodField()
    total_withdrawals = serializers.SerializerMethodField()
    closing_balance = serializers.SerializerMethodField()
    total_profit = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = SavingsCycle
        fields = [
            'id', 'name', 'start_date', 'end_date', 'status',
            'interest_rate', 'total_savings', 'total_withdrawals',
            'closing_balance', 'total_profit',
            'member_count', 'created_at', 'updated_at'
        ]

    def get_total_savings(self, obj):
        return float(obj.total_savings())

    def get_total_withdrawals(self, obj):
        return float(obj.total_withdrawals())

    def get_closing_balance(self, obj):
        return float(obj.closing_balance())

    def get_total_profit(self, obj):
        return float(obj.total_profit())

    def get_member_count(self, obj):
        return obj.member_count()


class CreateSavingsCycleSerializer(serializers.ModelSerializer):
    """
    Fully FREE cycle creation serializer.
    - No active-cycle restriction
    - Any date (past, present, or future)
    - Any status you choose
    - Name is auto-generated but can be overridden
    """

    name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = SavingsCycle
        fields = ['name', 'start_date', 'end_date', 'status', 'interest_rate']
        extra_kwargs = {
            'end_date': {'required': False},
            'status': {'required': False},
            'interest_rate': {'required': False},
        }

    def validate(self, data):
        # Auto-generate name from start_date if not provided
        if not data.get('name'):
            start = data.get('start_date')
            if start:
                data['name'] = start.strftime("%B %Y")
        return data

    def create(self, validated_data):
        return SavingsCycle.objects.create(**validated_data)


class SavingsEntrySerializer(serializers.ModelSerializer):
    """Full read serializer for savings entries"""

    member_name = serializers.SerializerMethodField()
    member_id = serializers.CharField(source='member.membership_id', read_only=True)
    cycle_name = serializers.CharField(source='cycle.name', read_only=True)
    cycle_status = serializers.CharField(source='cycle.status', read_only=True)
    remaining_amount = serializers.SerializerMethodField()
    is_withdrawn_from = serializers.SerializerMethodField()

    class Meta:
        model = SavingsEntry
        fields = [
            'id', 'member', 'member_id', 'member_name', 'cycle',
            'cycle_name', 'cycle_status', 'amount', 'withdrawn_amount',
            'remaining_amount', 'date', 'comment', 'is_late_entry',
            'is_withdrawn_from', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'withdrawn_amount', 'created_at', 'updated_at']

    def get_remaining_amount(self, obj):
        return float(obj.remaining_amount)

    def get_member_name(self, obj):
        return obj.member.user.get_full_name()

    def get_is_withdrawn_from(self, obj):
        return obj.is_withdrawn_from


class CreateSavingsEntrySerializer(serializers.Serializer):
    """
    Create a savings entry.

    Normal flow: picks the active cycle automatically (unchanged behaviour).

    Late-save flow: pass an explicit `cycle` id (any cycle, including a
    closed one) to backdate this saving into that specific past cycle.
    It is then saved permanently under that cycle, shows up in that
    cycle's own history/totals, is deletable like any entry, and has
    ZERO effect on the currently active cycle's numbers.
    """

    member = serializers.PrimaryKeyRelatedField(queryset=MemberProfile.objects.all())
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    date = serializers.DateField()
    comment = serializers.CharField(required=False, allow_blank=True)
    cycle = serializers.PrimaryKeyRelatedField(
        queryset=SavingsCycle.objects.all(), required=False, allow_null=True
    )

    def validate(self, data):
        explicit_cycle = data.pop('cycle', None)

        if explicit_cycle is not None:
            # Late-save into a specific (usually past) cycle.
            data['cycle'] = explicit_cycle
            data['is_late_entry'] = explicit_cycle.status != 'active'
        else:
            active_cycle = SavingsCycle.objects.filter(status='active').first()
            if not active_cycle:
                raise serializers.ValidationError("No active savings cycle found")
            data['cycle'] = active_cycle
            data['is_late_entry'] = False

        return data

    def create(self, validated_data):
        return SavingsEntry.objects.create(**validated_data)


class WithdrawalAllocationSerializer(serializers.ModelSerializer):
    """Read-only breakdown of which day's deposit a withdrawal drew from"""

    deposit_date = serializers.DateField(source='savings_entry.date', read_only=True)

    class Meta:
        model = WithdrawalAllocation
        fields = ['id', 'savings_entry', 'deposit_date', 'amount']


class WithdrawalSerializer(serializers.ModelSerializer):
    """Full read serializer for withdrawals, including the deposit-day breakdown"""

    member_name = serializers.SerializerMethodField()
    member_id = serializers.CharField(source='member.membership_id', read_only=True)
    cycle_name = serializers.CharField(source='cycle.name', read_only=True)
    allocations = WithdrawalAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = Withdrawal
        fields = [
            'id', 'member', 'member_id', 'member_name', 'cycle', 'cycle_name',
            'amount', 'date', 'reason', 'allocations', 'created_by', 'created_at'
        ]
        read_only_fields = ['id', 'cycle', 'created_by', 'created_at']

    def get_member_name(self, obj):
        return obj.member.user.get_full_name()


class CreateWithdrawalSerializer(serializers.Serializer):
    """
    Withdraw an amount from a member's balance.

    ✅ FIX: withdrawals are now scoped to the currently active cycle. The
    "available balance" check and the FIFO draw-down BOTH only look at
    deposits made within THIS SAME cycle — a withdrawal can never reach
    back into a previous, already-settled cycle's deposits. This is what
    keeps a brand-new cycle showing a clean, correct balance instead of
    going negative because of unrelated withdrawal history.

    Consumes the OLDEST deposits first (FIFO) within the active cycle:
    e.g. 10,000 saved on Day 1 and 10,000 on Day 2 of THIS cycle,
    withdrawing 15,000 fully empties Day 1's entry and takes 5,000 from
    Day 2's entry. Nothing is deleted — each deposit row keeps its
    original amount, only `withdrawn_amount` increases, and this
    withdrawal is logged with a reason so the money's movement stays
    visible.
    """

    member = serializers.PrimaryKeyRelatedField(queryset=MemberProfile.objects.all())
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    date = serializers.DateField()
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, data):
        member = data['member']
        amount = data['amount']

        active_cycle = SavingsCycle.objects.filter(status='active').first()
        if not active_cycle:
            raise serializers.ValidationError("No active savings cycle found")
        data['cycle'] = active_cycle

        # ✅ Only THIS cycle's deposits count as available to withdraw.
        available = SavingsEntry.objects.filter(
            member=member, cycle=active_cycle
        ).aggregate(
            total=Sum(F('amount') - F('withdrawn_amount'))
        )['total'] or Decimal('0.00')

        if amount > available:
            raise serializers.ValidationError(
                f"Insufficient balance in the current cycle. "
                f"Available balance is {available}."
            )
        return data

    @transaction.atomic
    def create(self, validated_data):
        member = validated_data['member']
        cycle = validated_data['cycle']
        amount_to_withdraw = validated_data['amount']
        reason = validated_data.get('reason') or 'Withdraw to be refilled'
        created_by = self.context['request'].user if self.context.get('request') else None

        withdrawal = Withdrawal.objects.create(
            member=member,
            cycle=cycle,
            amount=amount_to_withdraw,
            date=validated_data['date'],
            reason=reason,
            created_by=created_by,
        )

        # Oldest deposits first (FIFO), locking rows to avoid race conditions.
        # ✅ Scoped to this cycle only — never touches another cycle's entries.
        entries = list(
            SavingsEntry.objects.select_for_update()
            .filter(member=member, cycle=cycle)
            .order_by('date', 'created_at')
        )

        remaining_to_withdraw = amount_to_withdraw
        for entry in entries:
            if remaining_to_withdraw <= 0:
                break
            entry_remaining = entry.amount - entry.withdrawn_amount
            if entry_remaining <= 0:
                continue

            take = min(entry_remaining, remaining_to_withdraw)
            entry.withdrawn_amount = entry.withdrawn_amount + take
            entry.save(update_fields=['withdrawn_amount', 'updated_at'])

            WithdrawalAllocation.objects.create(
                withdrawal=withdrawal,
                savings_entry=entry,
                amount=take,
            )
            remaining_to_withdraw -= take

        return withdrawal