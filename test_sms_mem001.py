#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "harvest_haven.settings")
django.setup()

from authentication.models import MemberProfile
from savings.models import SavingsEntry, SavingsCycle
from savings.sms_service import SMSService
from django.db.models import Sum
from datetime import date

# Get member MEM001
member = MemberProfile.objects.get(membership_id='MEM001')
print(f"\n👤 Member: {member.user.first_name} {member.user.last_name}")
print(f"   Phone: {member.user.phone_number}")

# Get active cycle
active_cycle = SavingsCycle.objects.filter(status='active').first()
print(f"\n🔄 Cycle: {active_cycle.name if active_cycle else 'No active cycle'}")

# Get cycle total
if active_cycle:
    cycle_total = SavingsEntry.objects.filter(
        member=member, cycle=active_cycle
    ).aggregate(total=Sum('amount'))['total'] or 0
    print(f"💰 Cycle Total: UGX {cycle_total:,.0f}")

# Send SMS
print(f"\n📤 Sending SMS...")
success, msg = SMSService.send_savings_notification(
    member=member,
    amount=50000,
    date=date.today()
)

print(f"\n{'✅' if success else '❌'} Result: {msg}")