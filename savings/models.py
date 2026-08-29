from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from authentication.models import User, MemberProfile


class SavingsCycle(models.Model):
    """Savings cycle - fully flexible, no restrictions"""

    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ]

    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('18.4'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'savings_cycles'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.status})"

    def total_savings(self):
        total = self.savings_entries.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    # ✅ NEW: withdrawals are now scoped to a cycle, so this only sums
    # withdrawals actually made *within* this cycle.
    def total_withdrawals(self):
        total = self.withdrawals.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    def closing_balance(self):
        return self.total_savings() - self.total_withdrawals()

    def total_profit(self):
        total = self.total_savings()
        if not isinstance(total, Decimal):
            total = Decimal(str(total))
        return total * (Decimal(str(self.interest_rate)) / Decimal('100'))

    def member_count(self):
        return self.savings_entries.values('member').distinct().count()

    def previous_cycle(self):
        """The cycle immediately before this one, by start_date. Used purely
        for the informational 'carry-forward' figure — it is NEVER pulled
        into this cycle's own totals."""
        return SavingsCycle.objects.filter(
            start_date__lt=self.start_date
        ).order_by('-start_date').first()


class SavingsEntry(models.Model):
    """Individual savings entry"""

    member = models.ForeignKey(
        MemberProfile,
        on_delete=models.CASCADE,
        related_name='savings_entries'
    )
    cycle = models.ForeignKey(
        SavingsCycle,
        on_delete=models.CASCADE,
        related_name='savings_entries'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    # ✅ How much of this specific day's deposit has been withdrawn so far.
    # The deposit row itself is never deleted by a withdrawal — this just
    # tracks how much of it remains, so the saving history stays visible.
    withdrawn_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    date = models.DateField()
    comment = models.TextField(blank=True, null=True)

    # ✅ NEW: marks an entry deliberately backdated into a past/closed cycle
    # via the "late save" tool, as opposed to a normal same-cycle deposit.
    # Purely informational — cycle scoping already keeps it out of the
    # active cycle's totals regardless of this flag.
    is_late_entry = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_savings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'savings_entries'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.member.membership_id} - {self.amount} on {self.date}"

    @property
    def remaining_amount(self):
        return self.amount - self.withdrawn_amount

    @property
    def is_withdrawn_from(self):
        """True if any withdrawal has ever drawn from this specific deposit.
        Used to block deletion of an entry that's part of a withdrawal's
        FIFO trail, which would corrupt that history."""
        return self.withdrawal_allocations.exists()


class Withdrawal(models.Model):
    """A withdrawal made by a member. Doesn't delete any deposit — it draws
    down the oldest deposits first (FIFO) via WithdrawalAllocation rows, and
    always records a reason so the money's movement stays visible.

    ✅ FIX: withdrawals are now scoped to a SavingsCycle, exactly like
    SavingsEntry. This is what makes a new cycle start completely clean:
    a withdrawal made in the new cycle can only draw down deposits made in
    that SAME cycle, and only ever appears in that cycle's own totals.
    Older cycles' deposits and withdrawals are never touched by anything
    happening in the new cycle.
    """

    member = models.ForeignKey(
        MemberProfile,
        on_delete=models.CASCADE,
        related_name='withdrawals'
    )
    cycle = models.ForeignKey(
        SavingsCycle,
        on_delete=models.CASCADE,
        related_name='withdrawals',
        null=True,   # null=True only to allow the migration to run against
        blank=True,  # existing rows; see backfill script — new rows always get one.
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    date = models.DateField()
    reason = models.CharField(max_length=255, default='Withdraw to be refilled')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_withdrawals'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'withdrawals'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.member.membership_id} withdrew {self.amount} on {self.date}"


class WithdrawalAllocation(models.Model):
    """Records exactly which deposit-day entry a withdrawal drew from, and
    how much it took from that entry. A single withdrawal can span several
    of these rows when it eats into more than one day's savings.
    """

    withdrawal = models.ForeignKey(
        Withdrawal,
        on_delete=models.CASCADE,
        related_name='allocations'
    )
    savings_entry = models.ForeignKey(
        SavingsEntry,
        on_delete=models.CASCADE,
        related_name='withdrawal_allocations'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'withdrawal_allocations'

    def __str__(self):
        return f"{self.amount} from {self.savings_entry.date} -> withdrawal #{self.withdrawal_id}"