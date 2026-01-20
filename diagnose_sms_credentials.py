#!/usr/bin/env python
"""
Simple SMS test with MEM001 - Shows ACTIVE CYCLE total
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "harvest_haven.settings")
django.setup()

from authentication.models import MemberProfile
from savings.models import SavingsEntry, SavingsCycle
from savings.sms_service import SMSService
from django.db.models import Sum
from datetime import date


def main():
    print("\n" + "="*70)
    print("📱 SMS TEST - MEMBER MEM001")
    print("="*70)
    
    # Get member MEM001
    try:
        member = MemberProfile.objects.select_related('user').get(
            membership_id='MEM001'
        )
    except MemberProfile.DoesNotExist:
        print("\n❌ Member MEM001 not found!")
        print("   Available members:")
        members = MemberProfile.objects.filter(is_active_member=True)[:5]
        for m in members:
            print(f"      • {m.membership_id}: {m.user.first_name}")
        return
    
    print(f"\n👤 Test Member:")
    print(f"   Name: {member.user.first_name} {member.user.last_name}")
    print(f"   Phone: {member.user.phone_number}")
    print(f"   ID: {member.membership_id}")
    
    # Get active cycle
    active_cycle = SavingsCycle.objects.filter(status='active').first()
    
    if not active_cycle:
        print("\n❌ No active cycle found!")
        return
    
    print(f"\n🔄 Active Cycle:")
    print(f"   Name: {active_cycle.name}")
    print(f"   Status: {active_cycle.status}")
    
    # Calculate ACTIVE CYCLE total (what SMS will show)
    cycle_total = SavingsEntry.objects.filter(
        member=member,
        cycle=active_cycle
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Calculate LIFETIME total (for comparison)
    lifetime_total = SavingsEntry.objects.filter(
        member=member
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    print(f"\n💰 Savings Summary:")
    print(f"   This Cycle ({active_cycle.name}): UGX {cycle_total:,.0f} ✅")
    print(f"   Lifetime Total: UGX {lifetime_total:,.0f}")
    print(f"   SMS will show: UGX {cycle_total:,.0f} (cycle total)")
    
    # Test amount
    test_amount = 50000
    
    print(f"\n📤 Sending Test SMS...")
    print(f"   Test Deposit: UGX {test_amount:,.0f}")
    
    # Send SMS
    success, message = SMSService.send_savings_notification(
        member=member,
        amount=test_amount,
        date=date.today()
    )
    
    print("\n" + "="*70)
    if success:
        print("✅ SMS SENT SUCCESSFULLY!")
        print(f"   Response: {message}")
        print(f"\n   SMS shows cycle total: UGX {cycle_total:,.0f}")
        print(f"   Cycle: {active_cycle.name}")
        print("\n   Check the console above or your phone for the SMS")
    else:
        print("❌ SMS FAILED!")
        print(f"   Error: {message}")
    print("="*70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()