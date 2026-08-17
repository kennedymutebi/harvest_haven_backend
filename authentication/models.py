from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from datetime import timedelta
import random
import string
import uuid


class User(AbstractUser):
    """Custom User model for Harvest Haven Sacco"""
    
    # ✅ FIXED: Email is unique but nullable (for members who don't login)
    email = models.EmailField(unique=True, blank=True, null=True)
    
    phone_number = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="Phone number must be entered in the format: '+256700123456'. Up to 15 digits allowed."
            )
        ],
        unique=True,  # still unique when provided
        blank=True,
        null=True  # ✅ Optional now — members can be registered without a phone number
    )
    
    # Only admin approval is needed now
    is_admin_approved = models.BooleanField(default=False)
    
    # ✅ FIXED: Use phone_number for authentication for members, email for admins
    USERNAME_FIELD = 'username'  # Keep username as login field
    REQUIRED_FIELDS = ['first_name', 'last_name']  # Remove email from required
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return self.email or self.username or self.phone_number
    
    def can_login(self):
        """Check if user can login (only admins need to login)"""
        return self.is_admin_approved and self.is_active and self.email is not None
    
    def is_member(self):
        """Check if user is a member (has profile but no email)"""
        return hasattr(self, 'profile') and self.email is None


class Collector(models.Model):
    """A person who collects savings from members in the field.
    Created and managed by an admin. Collectors do not log in —
    this is just a name + phone number the admin uses to organize members."""

    name = models.CharField(max_length=150)
    phone_number = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="Phone number must be entered in the format: '+256700123456'. Up to 15 digits allowed."
            )
        ],
        blank=True,
        null=True
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='collectors_created'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'collectors'
        ordering = ['name']

    def __str__(self):
        return self.name


class MemberProfile(models.Model):
    """Extended profile information for members"""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    membership_id = models.CharField(max_length=10, unique=True, editable=False)
    place_of_residence = models.CharField(max_length=100, blank=True, null=True)  # ✅ Optional now
    date_joined = models.DateField(auto_now_add=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    is_active_member = models.BooleanField(default=True)

    # Tracks which admin account created this record (audit trail only).
    registered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registered_members'
    )

    # The Collector this member is attached to — chosen from a dropdown
    # by the admin when creating the member. Determines whose "people"
    # this member counts toward in daily/monthly savings summaries.
    collector = models.ForeignKey(
        Collector,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )
    
    # Additional fields
    date_of_birth = models.DateField(blank=True, null=True)
    national_id = models.CharField(max_length=20, blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'member_profiles'
        verbose_name = 'Member Profile'
        verbose_name_plural = 'Member Profiles'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.membership_id}"
    
    def save(self, *args, **kwargs):
        if not self.membership_id:
            # Generate membership ID
            last_member = MemberProfile.objects.all().order_by('id').last()
            if last_member:
                last_id = int(last_member.membership_id[3:])
                new_id = last_id + 1
            else:
                new_id = 1
            self.membership_id = f'MEM{new_id:03d}'
        super().save(*args, **kwargs)


class OTPToken(models.Model):
    """OTP for login verification"""
    
    OTP_TYPE_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_tokens')
    otp = models.CharField(max_length=6)
    otp_type = models.CharField(max_length=10, choices=OTP_TYPE_CHOICES, default='email')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    
    class Meta:
        db_table = 'otp_tokens'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp}"
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return (not self.is_used and 
                timezone.now() < self.expires_at and 
                self.attempts < self.max_attempts)
    
    @staticmethod
    def generate_otp():
        """Generate a random 6-digit OTP"""
        from django.conf import settings
        otp_length = getattr(settings, 'OTP_LENGTH', 6)
        return ''.join(random.choices(string.digits, k=otp_length))
    
    def save(self, *args, **kwargs):
        if not self.otp:
            self.otp = self.generate_otp()
        if not self.expires_at:
            from django.conf import settings
            expiry_minutes = getattr(settings, 'OTP_EXPIRY_MINUTES', 10)
            self.expires_at = timezone.now() + timedelta(minutes=expiry_minutes)
        super().save(*args, **kwargs)


class PendingApproval(models.Model):
    """Track pending user approvals"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='approval_request')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approval_token = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.EmailField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    class Meta:
        db_table = 'pending_approvals'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.email} - {self.status}"
    
    @staticmethod
    def generate_approval_token():
        """Generate a random approval token"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    def save(self, *args, **kwargs):
        if not self.approval_token:
            self.approval_token = self.generate_approval_token()
        super().save(*args, **kwargs)


class PasswordResetToken(models.Model):
    """Token for password reset via email link"""
    
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_tokens')
    token      = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used    = models.BooleanField(default=False)

    class Meta:
        db_table = 'password_reset_tokens'
        ordering = ['-created_at']

    def is_valid(self):
        return not self.is_used and timezone.now() < self.created_at + timedelta(minutes=30)

    def __str__(self):
        return f"ResetToken({self.user.email})"