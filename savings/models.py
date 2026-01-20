from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from authentication.models import User, MemberProfile


class SavingsCycle(models.Model):
    """Monthly savings cycle"""
    
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ]
    
    name = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # ✅ Nullable - set when cycle closes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    interest_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=18.4,
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
        """Calculate total savings for this cycle"""
        total = self.savings_entries.aggregate(
            total=models.Sum('amount')
        )['total']
        return total or Decimal('0.00')
    
    def total_profit(self):
        """Calculate total profit for this cycle"""
        total = self.total_savings()
        # Convert to Decimal if needed
        if not isinstance(total, Decimal):
            total = Decimal(str(total))
        # FIXED LINE: Ensure interest_rate is Decimal before division
        profit = total * (Decimal(str(self.interest_rate)) / Decimal('100'))
        return profit
    
    def member_count(self):
        """Count unique members in this cycle"""
        return self.savings_entries.values('member').distinct().count()


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
    date = models.DateField()
    comment = models.TextField(blank=True, null=True)
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
        return f"{self.member.membership_id} - ${self.amount} on {self.date}"