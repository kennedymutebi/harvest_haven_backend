#!/usr/bin/env python
"""
Simple SMS test that actually works with production
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "harvest_haven.settings")
django.setup()

from django.conf import settings
import africastalking


def send_test_sms(phone_number, message):
    """Send a test SMS using Africa's Talking directly"""
    
    print("\n" + "="*70)
    print("📱 SENDING TEST SMS")
    print("="*70)
    
    # Get credentials
    username = settings.AFRICASTALKING_USERNAME
    api_key = settings.AFRICASTALKING_API_KEY
    
    print(f"Username: {username}")
    print(f"To: {phone_number}")
    print(f"Message: {message}")
    print(f"Message length: {len(message)} characters")
    
    # Initialize
    africastalking.initialize(username, api_key)
    sms = africastalking.SMS
    
    # Send WITHOUT sender_id (let Africa's Talking use default)
    try:
        print("\n📤 Sending SMS...")
        response = sms.send(
            message=message,
            recipients=[phone_number]
            # NOTE: No sender_id parameter - uses default
        )
        
        print(f"📥 Response: {response}")
        
        if response['SMSMessageData']['Recipients']:
            recipient = response['SMSMessageData']['Recipients'][0]
            
            if recipient['status'] == 'Success':
                print(f"\n✅ SMS SENT SUCCESSFULLY!")
                print(f"   Message ID: {recipient['messageId']}")
                print(f"   Status: {recipient['status']}")
                print(f"   Cost: {recipient.get('cost', 'N/A')}")
                print(f"\n📱 Check your phone: {phone_number}")
                return True
            else:
                print(f"\n❌ SMS FAILED!")
                print(f"   Status: {recipient['status']}")
                print(f"   Error: {recipient.get('statusCode', 'Unknown')}")
                return False
        else:
            print("\n❌ No recipients in response")
            return False
            
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False


def main():
    print("\n" + "="*70)
    print("🧪 SIMPLE SMS TEST - AFRICA'S TALKING PRODUCTION")
    print("="*70)
    
    # Configuration
    phone_number = "+256752682559"
    message = "Hello Kennedy! This is a test SMS from Harvest Haven SACCO. Your production SMS is working! 🎉"
    
    # Check balance first
    try:
        username = settings.AFRICASTALKING_USERNAME
        api_key = settings.AFRICASTALKING_API_KEY
        
        africastalking.initialize(username, api_key)
        application = africastalking.Application
        user_data = application.fetch_application_data()
        balance = user_data['UserData']['balance']
        
        print(f"\n💰 Current Balance: {balance}")
        print(f"   SMS Cost: ~30 UGX per message")
        
    except Exception as e:
        print(f"\n⚠️  Could not fetch balance: {e}")
    
    # Confirm
    print(f"\n⚠️  About to send REAL SMS:")
    print(f"   To: {phone_number}")
    print(f"   Cost: ~30 UGX")
    
    confirm = input("\nContinue? (yes/no): ")
    
    if confirm.lower() != 'yes':
        print("\n❌ Cancelled by user")
        return
    
    # Send SMS
    success = send_test_sms(phone_number, message)
    
    if success:
        print("\n" + "="*70)
        print("🎉 SUCCESS! SMS SENT!")
        print("="*70)
        print("\n✅ Your Africa's Talking production SMS is working!")
        print("✅ Check phone 0752682559 for the message")
        print("\n📝 NEXT STEPS:")
        print("   1. You can now use SMS in your application")
        print("   2. Monitor your balance at: https://account.africastalking.com")
        print("   3. Top up when balance is low")
        print("   4. (Optional) Request custom Sender ID for branded messages")
        print("\n💡 TIP: To use custom sender ID like 'SACCO':")
        print("   - Go to https://account.africastalking.com")
        print("   - Navigate to SMS → Sender IDs")
        print("   - Request 'SACCO' or 'HarvestSACCO'")
        print("   - Wait for approval (1-2 business days)")
        print("   - Then update AFRICASTALKING_SENDER_ID in .env")
    else:
        print("\n" + "="*70)
        print("❌ SMS FAILED")
        print("="*70)
        print("\nPossible issues:")
        print("1. Invalid phone number format")
        print("2. Insufficient balance")
        print("3. Network issues")
        print("\nCheck the error message above for details")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
    except Exception as e:
        print(f"\n\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()