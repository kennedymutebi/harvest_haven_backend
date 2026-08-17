from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.conf import settings
from .models import OTPToken, PendingApproval


def send_admin_approval_email(user, approval):
    """Send approval request to admin"""
    
    # Build approval URLs
    approve_url = f"{settings.BACKEND_URL}/api/auth/approve-user/{approval.approval_token}/?action=approve"
    reject_url = f"{settings.BACKEND_URL}/api/auth/approve-user/{approval.approval_token}/?action=reject"
    
    subject = f'New Member Registration Approval Required - {user.get_full_name()}'
    
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #16a34a;">New Member Registration</h2>
                <p>A new user has registered and requires your approval:</p>
                
                <div style="background-color: #f5f5f5; padding: 20px; border-radius: 5px; margin: 20px 0;">
                    <p><strong>Name:</strong> {user.first_name} {user.last_name}</p>
                    <p><strong>Email:</strong> {user.email}</p>
                    <p><strong>Phone:</strong> {user.phone_number or 'Not provided'}</p>
                    <p><strong>Username:</strong> {user.username}</p>
                    <p><strong>Membership ID:</strong> {user.profile.membership_id}</p>
                    <p><strong>Place of Residence:</strong> {user.profile.place_of_residence}</p>
                    <p><strong>Registration Date:</strong> {user.date_joined.strftime('%B %d, %Y %I:%M %p')}</p>
                </div>
                
                <p><strong>Please approve or reject this registration:</strong></p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{approve_url}" 
                       style="background-color: #16a34a; color: white; padding: 12px 30px; 
                              text-decoration: none; border-radius: 5px; display: inline-block; margin: 0 10px;">
                        ✓ Approve
                    </a>
                    <a href="{reject_url}" 
                       style="background-color: #dc2626; color: white; padding: 12px 30px; 
                              text-decoration: none; border-radius: 5px; display: inline-block; margin: 0 10px;">
                        ✗ Reject
                    </a>
                </div>
            </div>
        </body>
    </html>
    """
    
    text_content = strip_tags(html_content)
    
    email = EmailMultiAlternatives(
        subject, 
        text_content, 
        settings.DEFAULT_FROM_EMAIL, 
        [settings.ADMIN_EMAIL]
    )
    email.attach_alternative(html_content, "text/html")
    email.send()


def send_approval_status_email(user, approved, reason=None):
    """Send approval status to user"""
    
    if approved:
        subject = 'Account Approved - Harvest Haven SACCO'
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #16a34a;">Account Approved! 🎉</h2>
                    <p>Hello {user.first_name},</p>
                    <p>Your Harvest Haven SACCO account has been approved by the administrator.</p>
                    <p><strong>Your Membership ID:</strong> {user.profile.membership_id}</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{settings.FRONTEND_URL}/login" 
                           style="background-color: #16a34a; color: white; padding: 12px 30px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Log In Now
                        </a>
                    </div>
                </div>
            </body>
        </html>
        """
    else:
        subject = 'Account Registration Update - Harvest Haven SACCO'
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #dc2626;">Account Registration Update</h2>
                    <p>Hello {user.first_name},</p>
                    <p>We regret to inform you that your account registration was not approved.</p>
                    {f'<p><strong>Reason:</strong> {reason}</p>' if reason else ''}
                    <p>If you have any questions, please contact support.</p>
                </div>
            </body>
        </html>
        """
    
    text_content = strip_tags(html_content)
    
    email = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [user.email])
    email.attach_alternative(html_content, "text/html")
    email.send()


def send_otp_email(user, otp):
    """Send OTP to user via email"""
    
    subject = 'Your Login OTP - Harvest Haven SACCO'
    
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #16a34a;">Login Verification Code</h2>
                <p>Hello {user.first_name},</p>
                <p>Your One-Time Password (OTP) for Harvest Haven SACCO is:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <div style="background-color: #f5f5f5; padding: 20px; border-radius: 5px; 
                                display: inline-block; font-size: 32px; font-weight: bold; 
                                letter-spacing: 10px; color: #16a34a;">
                        {otp}
                    </div>
                </div>
                <p style="color: #666; font-size: 14px;">
                    This OTP will expire in {settings.OTP_EXPIRY_MINUTES} minutes.
                </p>
            </div>
        </body>
    </html>
    """
    
    text_content = strip_tags(html_content)
    
    email = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [user.email])
    email.attach_alternative(html_content, "text/html")
    email.send()


def send_otp_sms(user, otp):
    """Send OTP to user via SMS (Optional - requires Twilio)"""
    
    try:
        from twilio.rest import Client
        
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        message = client.messages.create(
            body=f"Your Harvest Haven SACCO login OTP is: {otp}. Valid for {settings.OTP_EXPIRY_MINUTES} minutes. Do not share this code.",
            from_=settings.TWILIO_PHONE_NUMBER,
            to=user.phone_number
        )
        return True
    except Exception as e:
        print(f"SMS sending failed: {e}")
        return False
def send_password_reset_email(user, reset_token):
    """Send password reset link to user — matches your existing email style"""

    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={reset_token.token}"

    subject = 'Reset Your Password - Harvest Haven SACCO'

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #16a34a;">Password Reset Request</h2>
                <p>Hello {user.first_name},</p>
                <p>We received a request to reset your Harvest Haven SACCO password.
                   Click the button below to choose a new password:</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}"
                       style="background-color: #16a34a; color: white; padding: 14px 36px;
                              text-decoration: none; border-radius: 5px;
                              display: inline-block; font-size: 16px; font-weight: bold;">
                        Reset My Password
                    </a>
                </div>

                <div style="background-color: #f5f5f5; padding: 16px;
                            border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 0; color: #555; font-size: 14px;">
                        ⏱ This link expires in <strong>30 minutes</strong>.<br>
                        🔒 If you did not request a password reset, ignore this email —
                        your account is safe.
                    </p>
                </div>

                <p style="color: #999; font-size: 12px;">
                    If the button above doesn't work, copy and paste this link into your browser:<br>
                    <a href="{reset_link}" style="color: #16a34a;">{reset_link}</a>
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                <p style="color: #999; font-size: 12px; text-align: center;">
                    Harvest Haven SACCO &mdash; Kampala, Uganda
                </p>
            </div>
        </body>
    </html>
    """

    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [user.email]
    )
    email.attach_alternative(html_content, "text/html")
    email.send()
