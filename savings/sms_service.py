# savings/sms_service.py
# Multi-provider SMS service supporting Twilio and Africa's Talking
# FIXED: SMS now shows total for ACTIVE CYCLE only (not lifetime)

from django.conf import settings
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class SMSService:
    """
    Handle SMS notifications using multiple providers
    Supports: Twilio, Africa's Talking
    Provider is selected via SMS_PROVIDER setting in .env
    """
    
    # Class variable to store initialized client
    _client = None
    _provider = None
    _initialized = False
    
    @classmethod
    def _initialize(cls):
        """Initialize the SMS provider (called once)"""
        if cls._initialized:
            return
        
        cls._provider = getattr(settings, 'SMS_PROVIDER', 'twilio').lower()
        
        try:
            if cls._provider == 'africastalking':
                import africastalking
                username = settings.AFRICASTALKING_USERNAME
                api_key = settings.AFRICASTALKING_API_KEY
                
                # Log initialization (without exposing full API key)
                masked_key = api_key[:10] + '...' + api_key[-10:] if len(api_key) > 20 else '***'
                logger.info(f"🔧 Initializing Africa's Talking with username: {username}")
                logger.info(f"🔑 API Key (masked): {masked_key}")
                
                africastalking.initialize(username, api_key)
                cls._client = africastalking.SMS
                
                # Confirm environment
                env = "PRODUCTION" if username != "sandbox" else "SANDBOX"
                logger.info(f"✅ Africa's Talking SMS initialized ({env} MODE)")
                
            elif cls._provider == 'twilio':
                from twilio.rest import Client
                account_sid = settings.TWILIO_ACCOUNT_SID
                auth_token = settings.TWILIO_AUTH_TOKEN
                cls._client = Client(account_sid, auth_token)
                logger.info("✅ Twilio SMS initialized")
                
            cls._initialized = True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize {cls._provider}: {str(e)}")
            cls._initialized = False
    
    @staticmethod
    def _normalize_phone_number(phone_number: str) -> str:
        """Normalize phone number to international format (+256...)"""
        if not phone_number:
            return phone_number
        
        # Remove spaces, dashes, parentheses
        phone_number = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Add Uganda country code if missing
        if not phone_number.startswith('+'):
            if phone_number.startswith('0'):
                phone_number = '+256' + phone_number[1:]
            elif phone_number.startswith('256'):
                phone_number = '+' + phone_number
            else:
                phone_number = '+256' + phone_number
        
        return phone_number
    
    @staticmethod
    def send_sms(phone_number: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS to phone number using configured provider
        
        Args:
            phone_number: Recipient phone number
            message: SMS message content
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        # Check if SMS is enabled
        if not getattr(settings, 'SMS_ENABLED', True):
            logger.info(f"SMS disabled. Would send to {phone_number}: {message}")
            return True, "SMS disabled in settings"
        
        # In development/DEBUG mode, just log the SMS
        if settings.DEBUG:
            return SMSService._mock_send(phone_number, message)
        
        # Initialize provider if not done
        SMSService._initialize()
        
        if not SMSService._initialized:
            logger.error("SMS provider not initialized")
            return False, "SMS provider not initialized"
        
        # Normalize phone number
        phone_number = SMSService._normalize_phone_number(phone_number)
        
        # Validate phone number format
        if not phone_number.startswith('+256') or len(phone_number) != 13:
            logger.error(f"Invalid phone number format: {phone_number}")
            return False, f"Invalid phone number format: {phone_number}"
        
        # Send via configured provider
        if SMSService._provider == 'africastalking':
            return SMSService._send_via_africastalking(phone_number, message)
        elif SMSService._provider == 'twilio':
            return SMSService._send_via_twilio(phone_number, message)
        else:
            return False, f"Unknown provider: {SMSService._provider}"
    
    @staticmethod
    def _mock_send(phone_number: str, message: str) -> Tuple[bool, str]:
        """Mock SMS for development"""
        provider = SMSService._provider or 'Not initialized'
        username = getattr(settings, 'AFRICASTALKING_USERNAME', 'N/A')
        env = "PRODUCTION" if username == "Harvest-haven" else "SANDBOX"
        
        print("\n" + "="*60)
        print("📱 SMS NOTIFICATION (DEVELOPMENT/DEBUG MODE)")
        print("="*60)
        print(f"Provider: {provider}")
        print(f"Environment: {env}")
        print(f"Username: {username}")
        print(f"To: {phone_number}")
        print(f"\nMessage:")
        print(message)
        print("="*60 + "\n")
        logger.info(f"Mock SMS sent to {phone_number} (DEBUG mode)")
        return True, "SMS sent (mock/debug mode)"
    
    @staticmethod
    def _send_via_africastalking(phone_number: str, message: str) -> Tuple[bool, str]:
        """Send SMS via Africa's Talking - NO SENDER ID"""
        try:
            username = getattr(settings, 'AFRICASTALKING_USERNAME', 'unknown')
            
            logger.info(f"📤 Sending SMS via Africa's Talking ({username})...")
            logger.info(f"   To: {phone_number}")
            logger.info(f"   Message length: {len(message)} chars")
            logger.info(f"   Sender ID: Not specified (using Africa's Talking default)")
            
            # Send WITHOUT sender_id parameter
            response = SMSService._client.send(
                message=message,
                recipients=[phone_number]
            )
            
            # Parse Africa's Talking response
            logger.info(f"📥 Response received: {response}")
            
            if response['SMSMessageData']['Recipients']:
                recipient = response['SMSMessageData']['Recipients'][0]
                
                if recipient['status'] == 'Success':
                    message_id = recipient['messageId']
                    cost = recipient.get('cost', 'N/A')
                    logger.info(f"✅ SMS sent successfully!")
                    logger.info(f"   Message ID: {message_id}")
                    logger.info(f"   Cost: {cost}")
                    logger.info(f"   To: {phone_number}")
                    return True, f"SMS sent successfully. ID: {message_id}"
                else:
                    error_msg = recipient.get('status', 'Unknown error')
                    logger.error(f"❌ Africa's Talking error: {error_msg}")
                    return False, error_msg
            else:
                logger.error("❌ No recipients in Africa's Talking response")
                return False, "No recipients in response"
                
        except Exception as e:
            logger.error(f"❌ Africa's Talking exception: {str(e)}", exc_info=True)
            return False, f"Africa's Talking error: {str(e)}"
    
    @staticmethod
    def _send_via_twilio(phone_number: str, message: str) -> Tuple[bool, str]:
        """Send SMS via Twilio"""
        try:
            from_number = settings.TWILIO_PHONE_NUMBER
            
            logger.info(f"📤 Sending SMS via Twilio to {phone_number}...")
            
            # Send SMS
            twilio_message = SMSService._client.messages.create(
                body=message,
                from_=from_number,
                to=phone_number
            )
            
            logger.info(f"✅ SMS sent via Twilio")
            logger.info(f"   SID: {twilio_message.sid}")
            logger.info(f"   Status: {twilio_message.status}")
            return True, f"SMS sent successfully. SID: {twilio_message.sid}"
            
        except Exception as e:
            logger.error(f"❌ Twilio SMS error: {str(e)}", exc_info=True)
            return False, str(e)
    
    # ============================================
    # BUSINESS-SPECIFIC SMS METHODS
    # ============================================
    
    @staticmethod
    def send_savings_notification(member, amount, date) -> Tuple[bool, str]:
        """
        Send savings confirmation SMS to member with ACTIVE CYCLE total
        
        Args:
            member: MemberProfile instance
            amount: Saved amount
            date: Date of savings
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        phone_number = member.user.phone_number
        
        if not phone_number:
            logger.warning(f"No phone number for member {member.membership_id}")
            return False, "No phone number"
        
        from .models import SavingsEntry, SavingsCycle
        from django.db.models import Sum
        
        # Get ACTIVE CYCLE
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            logger.warning("No active cycle found - using lifetime total")
            # Fallback to lifetime total if no active cycle
            total_savings = SavingsEntry.objects.filter(
                member=member
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = "Total"
        else:
            # Calculate total for ACTIVE CYCLE ONLY
            total_savings = SavingsEntry.objects.filter(
                member=member,
                cycle=active_cycle
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = active_cycle.name
        
        # Format message with active cycle total
        message = (
            f"Dear {member.user.first_name},\n"
            f"Deposit: UGX {amount:,.0f} on {date.strftime('%d/%m/%Y')}\n"
            f"Cycle total: UGX {total_savings:,.0f}\n"
            f"Cycle: {cycle_name}\n"
            f"ID: {member.membership_id}\n"
            f"Thank you - Harvest Haven SACCO"
        )
        
        logger.info(f"Sending SMS to {phone_number} - Cycle: {cycle_name}, Total: {total_savings}")
        
        return SMSService.send_sms(phone_number, message)
    
    @staticmethod
    def send_savings_update_notification(member, amount, date) -> Tuple[bool, str]:
        """
        Send SMS when savings entry is updated - ACTIVE CYCLE total
        
        Args:
            member: MemberProfile instance
            amount: Updated amount
            date: Date of savings
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        phone_number = member.user.phone_number
        
        if not phone_number:
            logger.warning(f"No phone number for member {member.membership_id}")
            return False, "No phone number"
        
        from .models import SavingsEntry, SavingsCycle
        from django.db.models import Sum
        
        # Get ACTIVE CYCLE
        active_cycle = SavingsCycle.objects.filter(status='active').first()
        
        if not active_cycle:
            # Fallback to lifetime total
            total_savings = SavingsEntry.objects.filter(
                member=member
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = "Total"
        else:
            # Calculate total for ACTIVE CYCLE ONLY
            total_savings = SavingsEntry.objects.filter(
                member=member,
                cycle=active_cycle
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = active_cycle.name
        
        message = (
            f"Dear {member.user.first_name},\n"
            f"Savings updated to UGX {amount:,.0f} for {date.strftime('%d/%m/%Y')}\n"
            f"Cycle total: UGX {total_savings:,.0f}\n"
            f"Cycle: {cycle_name}\n"
            f"ID: {member.membership_id}\n"
            f"- Harvest Haven SACCO"
        )
        
        return SMSService.send_sms(phone_number, message)
    
    @staticmethod
    def send_welcome_sms(member) -> Tuple[bool, str]:
        """
        Send welcome SMS to new member
        
        Args:
            member: MemberProfile instance
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        phone_number = member.user.phone_number
        
        if not phone_number:
            logger.warning(f"No phone number for member {member.membership_id}")
            return False, "No phone number"
        
        message = (
            f"Welcome to Harvest Haven SACCO, {member.user.first_name}!\n"
            f"Your Membership ID: {member.membership_id}\n"
            f"Start saving today and grow together."
        )
        
        return SMSService.send_sms(phone_number, message)
    
    @staticmethod
    def send_otp_sms(phone_number: str, otp_code: str) -> Tuple[bool, str]:
        """
        Send OTP verification SMS
        
        Args:
            phone_number: User's phone number
            otp_code: The OTP code to send
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        otp_expiry = getattr(settings, 'OTP_EXPIRY_MINUTES', 10)
        
        message = (
            f"Your Harvest Haven SACCO verification code is: {otp_code}. "
            f"Valid for {otp_expiry} minutes. "
            f"Do not share this code."
        )
        
        return SMSService.send_sms(phone_number, message)
    
    @staticmethod
    def send_approval_notification(user, approved: bool) -> Tuple[bool, str]:
        """
        Send account approval/rejection notification
        
        Args:
            user: User instance
            approved: True if approved, False if rejected
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        phone_number = user.phone_number
        
        if not phone_number:
            logger.warning(f"No phone number for user {user.username}")
            return False, "No phone number"
        
        if approved:
            message = (
                f"Congratulations {user.first_name}! "
                f"Your Harvest Haven SACCO account has been approved. "
                f"You can now login and start managing your savings."
            )
        else:
            message = (
                f"Hello {user.first_name}, "
                f"your Harvest Haven SACCO registration was not approved. "
                f"Please contact the administrator for more information."
            )
        
        return SMSService.send_sms(phone_number, message)
    
    @staticmethod
    def send_cycle_notification(member, cycle_name: str, action: str = 'started') -> Tuple[bool, str]:
        """
        Send cycle-related notifications
        
        Args:
            member: MemberProfile instance
            cycle_name: Name of the cycle
            action: 'started', 'ending', 'closed'
            
        Returns:
            Tuple[bool, str]: (success, message/error)
        """
        phone_number = member.user.phone_number
        
        if not phone_number:
            return False, "No phone number"
        
        if action == 'started':
            message = (
                f"Hi {member.user.first_name}, "
                f"a new savings cycle '{cycle_name}' has started. "
                f"Start contributing today!"
            )
        elif action == 'ending':
            message = (
                f"Hi {member.user.first_name}, "
                f"the cycle '{cycle_name}' is ending soon. "
                f"Make your final contributions now."
            )
        elif action == 'closed':
            message = (
                f"Hi {member.user.first_name}, "
                f"the cycle '{cycle_name}' has been closed. "
                f"Thank you for your contributions!"
            )
        else:
            message = f"Cycle update: {cycle_name}"
        
        return SMSService.send_sms(phone_number, message)
    
    @staticmethod
    def get_provider_info() -> dict:
        """
        Get current SMS provider information (for admin dashboard)
        
        Returns:
            dict: Provider information including status and balance
        """
        SMSService._initialize()
        
        info = {
            'provider': SMSService._provider,
            'initialized': SMSService._initialized,
            'enabled': getattr(settings, 'SMS_ENABLED', True),
            'debug_mode': settings.DEBUG
        }
        
        if SMSService._provider == 'africastalking':
            info['username'] = getattr(settings, 'AFRICASTALKING_USERNAME', 'N/A')
            info['environment'] = 'PRODUCTION' if info['username'] == 'Harvest-haven' else 'SANDBOX'
            info['sender_id'] = 'Not specified (using default)'
        elif SMSService._provider == 'twilio':
            info['phone_number'] = getattr(settings, 'TWILIO_PHONE_NUMBER', 'N/A')
        
        return info