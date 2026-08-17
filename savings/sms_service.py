# savings/sms_service.py
# SMS Service — Primary provider: EgoSMS (Uganda)
# Delivers to ALL Uganda networks: MTN, Airtel, UTL
# Cost: UGX 20-35 per SMS | Top up via Mobile Money | No monthly fees
# Sign up: https://www.egosms.co
# API docs: https://developers.pahappa.com

from django.conf import settings
import logging
import requests
import json
import html as html_lib
from typing import Tuple

logger = logging.getLogger(__name__)


class SMSService:
    """
    SMS notifications via EgoSMS — Uganda's cheapest all-network SMS provider.

    Required .env settings:
        SMS_PROVIDER=egosms
        EGOSMS_USERNAME=your_username
        EGOSMS_PASSWORD=your_password
        EGOSMS_SENDER_ID=SMSAlert    (max 11 chars, no spaces)

    Optional:
        SMS_ENABLED=True   (set False to disable all SMS)
    """

    # ✅ FIXED: Updated to new EgoSMS API endpoint (comms.egosms.co)
    EGOSMS_URL = "https://comms.egosms.co/api/v1/json/"

    # ─── Phone Number Normalization ───────────────────────────────────────────

    @staticmethod
    def _normalize_phone_number(phone_number: str) -> str:
        """
        Normalize any Uganda number to 256XXXXXXXXX (no + prefix).
        EgoSMS expects numbers WITHOUT the + sign.

        Examples:
            0774123456    -> 256774123456
            +256774123456 -> 256774123456
            256774123456  -> 256774123456
        """
        if not phone_number:
            return phone_number

        phone = phone_number.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

        if phone.startswith('+'):
            phone = phone[1:]

        if phone.startswith('0') and len(phone) == 10:
            phone = '256' + phone[1:]

        if not phone.startswith('256'):
            phone = '256' + phone

        return phone

    @staticmethod
    def _validate_phone_number(phone_number: str) -> bool:
        """Validate normalized Uganda number: must be 256 + 9 digits = 12 chars total"""
        return (
            phone_number.startswith('256') and
            len(phone_number) == 12 and
            phone_number.isdigit()
        )

    # ─── Core Send ────────────────────────────────────────────────────────────

    @staticmethod
    def send_sms(phone_number: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS to a Uganda phone number via EgoSMS.

        Args:
            phone_number: Any Uganda format (077x, +256x, 256x)
            message: SMS text (max 160 chars per SMS unit)

        Returns:
            (True, success_message) or (False, error_message)
        """
        if not getattr(settings, 'SMS_ENABLED', True):
            logger.info(f"SMS disabled. Would send to {phone_number}: {message[:50]}...")
            return True, "SMS disabled in settings"

        if getattr(settings, 'DEBUG', False):
            return SMSService._mock_send(phone_number, message)

        normalized = SMSService._normalize_phone_number(phone_number)

        if not SMSService._validate_phone_number(normalized):
            logger.error(f"Invalid phone number: '{phone_number}' -> normalized: '{normalized}'")
            return False, f"Invalid Uganda phone number: {phone_number}"

        return SMSService._send_via_egosms(normalized, message)

    # ─── EgoSMS Provider ─────────────────────────────────────────────────────

    @staticmethod
    def _send_via_egosms(phone_number: str, message: str) -> Tuple[bool, str]:
        """
        Send via EgoSMS JSON API.
        Phone number must already be normalized to 256XXXXXXXXX format.

        API endpoint: POST https://comms.egosms.co/api/v1/json/
        Success: {"Status": "OK", "Cost": 35, "MsgFollowUpUniqueCode": "..."}
        Failure: {"Status": "Failed", "Message": "error reason"}
        """
        try:
            username  = settings.EGOSMS_USERNAME
            password  = settings.EGOSMS_PASSWORD
            sender_id = getattr(settings, 'EGOSMS_SENDER_ID', 'SMSAlert')

            payload = {
                "method": "SendSms",
                "userdata": {
                    "username": html_lib.escape(username),
                    "password": html_lib.escape(password),
                },
                "msgdata": [
                    {
                        "number":   phone_number,
                        "message":  html_lib.escape(message),
                        "senderid": html_lib.escape(sender_id),
                        "priority": "0",
                    }
                ]
            }

            logger.info(f"EgoSMS sending to {phone_number} | sender: {sender_id} | {len(message)} chars")

            response = requests.post(
                url=SMSService.EGOSMS_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=15,
            )

            logger.debug(f"EgoSMS raw response [{response.status_code}]: {response.text}")

            try:
                result = response.json()
            except ValueError:
                logger.error(f"EgoSMS non-JSON response: {response.text}")
                return False, f"EgoSMS unexpected response: {response.text[:100]}"

            status = result.get("Status", "")

            if status == "OK":
                cost   = result.get("Cost", "N/A")
                msg_id = result.get("MsgFollowUpUniqueCode", "N/A")
                logger.info(f"EgoSMS success -> {phone_number} | Cost: UGX {cost} | ID: {msg_id}")
                return True, f"SMS sent. Cost: UGX {cost} | ID: {msg_id}"
            else:
                error = result.get("Message", "Unknown error from EgoSMS")
                logger.error(f"EgoSMS failed -> {phone_number}: {error}")
                return False, f"EgoSMS error: {error}"

        except requests.Timeout:
            logger.error(f"EgoSMS timeout for {phone_number}")
            return False, "EgoSMS request timed out — check internet connection"

        except requests.ConnectionError:
            logger.error(f"EgoSMS connection error for {phone_number}")
            return False, "Could not connect to EgoSMS — check internet"

        except AttributeError as e:
            logger.error(f"EgoSMS config missing: {e}")
            return False, "EgoSMS not configured. Add EGOSMS_USERNAME and EGOSMS_PASSWORD to .env"

        except Exception as e:
            logger.error(f"EgoSMS unexpected error: {str(e)}", exc_info=True)
            return False, f"EgoSMS error: {str(e)}"

    # ─── Balance Check ────────────────────────────────────────────────────────

    @staticmethod
    def check_balance() -> Tuple[bool, str]:
        """
        Check EgoSMS account balance.
        Use this in your admin panel to know when to top up via Mobile Money.
        """
        if getattr(settings, 'DEBUG', False):
            return True, "Balance check skipped in DEBUG mode"

        try:
            payload = {
                "method": "Balance",
                "userdata": {
                    "username": html_lib.escape(settings.EGOSMS_USERNAME),
                    "password": html_lib.escape(settings.EGOSMS_PASSWORD),
                }
            }

            response = requests.post(
                url=SMSService.EGOSMS_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

            result = response.json()

            if result.get("Status") == "OK":
                balance = result.get("Balance", "N/A")
                logger.info(f"EgoSMS balance: UGX {balance}")
                return True, f"Balance: UGX {balance}"
            else:
                error = result.get("Message", "Unknown error")
                return False, f"Balance check failed: {error}"

        except Exception as e:
            logger.error(f"Balance check error: {str(e)}")
            return False, str(e)

    # ─── Mock for Development ─────────────────────────────────────────────────

    @staticmethod
    def _mock_send(phone_number: str, message: str) -> Tuple[bool, str]:
        """Prints SMS to console during development. Nothing is actually sent."""
        normalized = SMSService._normalize_phone_number(phone_number)
        sender_id  = getattr(settings, 'EGOSMS_SENDER_ID', 'SMSAlert')

        print("\n" + "=" * 65)
        print("  SMS (DEBUG MODE - not sent to real phone)")
        print("=" * 65)
        print(f"  From    : {sender_id}")
        print(f"  To      : {normalized}  (original: {phone_number})")
        print(f"  Length  : {len(message)} chars")
        print(f"  Message :\n")
        for line in message.split('\n'):
            print(f"    {line}")
        print("=" * 65 + "\n")

        logger.info(f"[MOCK SMS] To: {normalized} | {len(message)} chars")
        return True, "SMS sent (mock/debug mode)"

    # ─── Provider Info ────────────────────────────────────────────────────────

    @staticmethod
    def get_provider_info() -> dict:
        """Return EgoSMS provider info for admin dashboard."""
        return {
            'provider':     'EgoSMS (Pahappa Ltd, Kampala Uganda)',
            'username':     getattr(settings, 'EGOSMS_USERNAME',  'Not configured'),
            'sender_id':    getattr(settings, 'EGOSMS_SENDER_ID', 'SMSAlert'),
            'networks':     'MTN Uganda, Airtel Uganda, UTL',
            'cost_per_sms': 'UGX 20-35',
            'topup_method': 'MTN Mobile Money or Airtel Money',
            'enabled':      getattr(settings, 'SMS_ENABLED', True),
            'debug_mode':   getattr(settings, 'DEBUG', False),
            'dashboard':    'https://comms.egosms.co',
            'api_docs':     'https://developers.pahappa.com',
        }

    # ─── Business SMS Methods ─────────────────────────────────────────────────

    @staticmethod
    def send_savings_notification(member, amount, date) -> Tuple[bool, str]:
        """Send deposit confirmation SMS — shows active cycle total."""
        phone_number = member.user.phone_number
        if not phone_number:
            logger.warning(f"No phone number for member {member.membership_id}")
            return False, "No phone number"

        from .models import SavingsEntry, SavingsCycle
        from django.db.models import Sum

        active_cycle = SavingsCycle.objects.filter(status='active').first()
        if not active_cycle:
            total_savings = SavingsEntry.objects.filter(
                member=member
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = "All Time"
        else:
            total_savings = SavingsEntry.objects.filter(
                member=member, cycle=active_cycle
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = active_cycle.name

        message = (
            f"Dear {member.user.first_name},\n"
            f"Deposit: UGX {amount:,.0f} on {date.strftime('%d/%m/%Y')}\n"
            f"Cycle total: UGX {total_savings:,.0f}\n"
            f"Cycle: {cycle_name}\n"
            f"ID: {member.membership_id}\n"
            f"Thank you - Harvest Haven SACCO"
        )

        logger.info(f"Savings SMS -> {member.membership_id} | cycle: {cycle_name} | total: {total_savings:,.0f}")
        return SMSService.send_sms(phone_number, message)

    @staticmethod
    def send_savings_update_notification(member, amount, date) -> Tuple[bool, str]:
        """Send SMS when a savings entry is updated."""
        phone_number = member.user.phone_number
        if not phone_number:
            return False, "No phone number"

        from .models import SavingsEntry, SavingsCycle
        from django.db.models import Sum

        active_cycle = SavingsCycle.objects.filter(status='active').first()
        if not active_cycle:
            total_savings = SavingsEntry.objects.filter(
                member=member
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = "All Time"
        else:
            total_savings = SavingsEntry.objects.filter(
                member=member, cycle=active_cycle
            ).aggregate(total=Sum('amount'))['total'] or 0
            cycle_name = active_cycle.name

        message = (
            f"Dear {member.user.first_name},\n"
            f"Savings updated: UGX {amount:,.0f} for {date.strftime('%d/%m/%Y')}\n"
            f"Cycle total: UGX {total_savings:,.0f}\n"
            f"Cycle: {cycle_name}\n"
            f"ID: {member.membership_id}\n"
            f"- Harvest Haven SACCO"
        )
        return SMSService.send_sms(phone_number, message)

    @staticmethod
    def send_welcome_sms(member) -> Tuple[bool, str]:
        """Moved to email. SMS disabled for welcome messages."""
        return False, "Welcome notifications are sent via email"

    @staticmethod
    def send_otp_sms(phone_number: str, otp_code: str) -> Tuple[bool, str]:
        """Moved to email. SMS disabled for OTP."""
        return False, "OTP notifications are sent via email"

    @staticmethod
    def send_approval_notification(user, approved: bool) -> Tuple[bool, str]:
        """Moved to email. SMS disabled for approval notifications."""
        return False, "Approval notifications are sent via email"

    @staticmethod
    def send_cycle_notification(member, cycle_name: str, action: str = 'started') -> Tuple[bool, str]:
        """Moved to email. SMS disabled for cycle notifications."""
        return False, "Cycle notifications are sent via email"