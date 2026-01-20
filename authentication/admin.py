from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, MemberProfile, OTPToken, PendingApproval


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        'email', 'username', 'first_name', 'last_name',
        'verification_status', 'approval_status', 'is_staff', 'date_joined'
    ]
    list_filter = ['is_staff', 'is_superuser', 'is_active', 'is_admin_approved']
    search_fields = ['email', 'username', 'first_name', 'last_name']
    ordering = ['-date_joined']

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'phone_number')}),
        ('Verification', {'fields': ('is_admin_approved',)}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )

    def verification_status(self, obj):
        # If you no longer have email verification, use only admin approval
        if obj.is_admin_approved:
            return format_html('<span style="color: green;">✓ Approved</span>')
        return format_html('<span style="color: orange;">⏳ Pending</span>')
    verification_status.short_description = 'Verification Status'

    def approval_status(self, obj):
        if obj.is_admin_approved:
            return format_html('<span style="color: green;">✓ Approved</span>')
        return format_html('<span style="color: orange;">⏳ Pending</span>')
    approval_status.short_description = 'Approval Status'


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ['membership_id', 'user', 'place_of_residence', 'is_active_member', 'date_joined']
    list_filter = ['is_active_member', 'date_joined']
    search_fields = ['membership_id', 'user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['membership_id', 'date_joined', 'created_at', 'updated_at']
    ordering = ['-created_at']


@admin.register(OTPToken)
class OTPTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp', 'otp_type', 'created_at', 'expires_at', 'attempts', 'is_used', 'status']
    list_filter = ['otp_type', 'is_used', 'created_at']
    search_fields = ['user__email', 'otp']
    readonly_fields = ['otp', 'created_at', 'expires_at']
    ordering = ['-created_at']

    def status(self, obj):
        if obj.is_used:
            return format_html('<span style="color: gray;">Used</span>')
        elif obj.is_valid():
            return format_html('<span style="color: green;">Valid</span>')
        return format_html('<span style="color: red;">Expired/Max Attempts</span>')
    status.short_description = 'Status'


@admin.register(PendingApproval)
class PendingApprovalAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'created_at', 'reviewed_at', 'reviewed_by', 'action_buttons']
    list_filter = ['status', 'created_at', 'reviewed_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['approval_token', 'created_at', 'reviewed_at']
    ordering = ['-created_at']

    fieldsets = (
        ('User Information', {
            'fields': ('user', 'status')
        }),
        ('Review Information', {
            'fields': ('reviewed_at', 'reviewed_by', 'rejection_reason')
        }),
        ('System Information', {
            'fields': ('approval_token', 'created_at')
        }),
    )

    def action_buttons(self, obj):
        if obj.status == 'pending':
            approve_url = f'/api/auth/approve-user/{obj.approval_token}/?action=approve'
            reject_url = f'/api/auth/approve-user/{obj.approval_token}/?action=reject'
            return format_html(
                '<a class="button" href="{}" target="_blank">Approve</a> '
                '<a class="button" href="{}" target="_blank" style="background-color: #dc2626;">Reject</a>',
                approve_url, reject_url
            )
        return format_html('<span style="color: gray;">{}</span>', obj.status.capitalize())
    action_buttons.short_description = 'Actions'
