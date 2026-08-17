#!/usr/bin/env python
"""
Simple SMS test using EgoSMS (Harvest Haven SACCO)
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "harvest_haven.settings")
django.setup()

from django.conf import settings
from savings.sms_service import SMSService
from datetime import datetime


def send_test_sms():
    print("\n" + "="*70)
    print("📱 SENDING TEST SMS - EGOSMS")
    print("="*70)

    phone_number = "+256752682559"
    message = "Hello Kennedy! 🎉 Your EgoSMS integration is working perfectly for Harvest Haven SACCO."

    print(f"To: {phone_number}")
    print(f"Message: {message}")
    print(f"Length: {len(message)} chars")

    print("\n📤 Sending SMS via EgoSMS...")

    success, response = SMSService.send_sms(phone_number, message)

    print("\n📥 RESPONSE:")
    print(response)

    if success:
        print("\n✅ SMS SENT SUCCESSFULLY!")
        print(f"📱 Check phone: {phone_number}")
    else:
        print("\n❌ SMS FAILED!")
        print("Check logs or .env settings")


def check_balance():
    print("\n" + "="*70)
    print("💰 CHECKING EGOSMS BALANCE")
    print("="*70)

    success, response = SMSService.check_balance()

    print(response)

    if success:
        print("✅ Balance retrieved successfully")
    else:
        print("❌ Failed to get balance")


def main():
    print("\n🧪 EGOSMS TEST STARTED")

    print("\n1️⃣ Checking balance...")
    check_balance()

    print("\n2️⃣ Sending test SMS...")
    send_test_sms()

    print("\n" + "="*70)
    print("🎉 TEST COMPLETED")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")