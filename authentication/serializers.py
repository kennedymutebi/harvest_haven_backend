from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from .models import User, MemberProfile, OTPToken


class MemberProfileSerializer(serializers.ModelSerializer):
    """Serializer for member profile"""
    
    class Meta:
        model = MemberProfile
        fields = [
            'membership_id', 'place_of_residence', 'date_joined',
            'profile_picture', 'is_active_member', 'date_of_birth',
            'national_id', 'emergency_contact_name', 'emergency_contact_phone'
        ]
        read_only_fields = ['membership_id', 'date_joined']


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model"""
    
    profile = MemberProfileSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone_number', 'date_joined', 
            'is_admin_approved', 'profile'
        ]
        read_only_fields = ['id', 'date_joined', 'is_email_verified', 'is_admin_approved']


class SignUpSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True, label="Confirm Password")
    place_of_residence = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'password2',
            'first_name', 'last_name', 'phone_number', 'place_of_residence'
        ]
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'email': {'required': True},
        }
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        return attrs
    
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def create(self, validated_data):
        password2 = validated_data.pop('password2')
        place_of_residence = validated_data.pop('place_of_residence')
        
        # Create user (inactive until approved)
        user = User.objects.create_user(**validated_data)
        user.is_active = True  # Can be active but can't login until verified and approved
        user.save()
        
        # Create member profile
        MemberProfile.objects.create(
            user=user,
            place_of_residence=place_of_residence
        )
        
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login - Step 1: Credentials"""
    
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        
        if email and password:
            user = authenticate(request=self.context.get('request'),
                                username=email, password=password)
            
            if not user:
                raise serializers.ValidationError('Invalid email or password.')
            
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            
            # Remove this line because email verification no longer exists
            # if not user.is_email_verified:
            #     raise serializers.ValidationError('Please verify your email address first.')
            
            if not user.is_admin_approved:
                raise serializers.ValidationError('Your account is pending admin approval.')
            
        else:
            raise serializers.ValidationError('Must include "email" and "password".')
        
        attrs['user'] = user
        return attrs



class OTPVerifySerializer(serializers.Serializer):
    """Serializer for OTP verification - Step 2: OTP"""
    
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(required=True, max_length=6, min_length=6)
    
    def validate(self, attrs):
        email = attrs.get('email')
        otp = attrs.get('otp')
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError('Invalid credentials.')
        
        # Get the latest valid OTP
        otp_token = OTPToken.objects.filter(
            user=user,
            otp=otp,
            is_used=False
        ).order_by('-created_at').first()
        
        if not otp_token:
            raise serializers.ValidationError('Invalid or expired OTP.')
        
        # Check if expired
        if not otp_token.is_valid():
            raise serializers.ValidationError('OTP has expired.')
        
        # Check attempts BEFORE incrementing
        if otp_token.attempts >= otp_token.max_attempts:
            raise serializers.ValidationError('Maximum OTP attempts exceeded. Please request a new OTP.')
        
        # Increment attempts only after validation passes
        otp_token.attempts += 1
        otp_token.save()
        
        attrs['user'] = user
        attrs['otp_token'] = otp_token
        return attrs

class ResendOTPSerializer(serializers.Serializer):
    """Serializer for resending OTP"""
    
    email = serializers.EmailField(required=True)
    otp_type = serializers.ChoiceField(choices=['email', 'sms'], default='email')


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change"""
    
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True, write_only=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({"new_password": "Password fields didn't match."})
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request"""
    
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("No user found with this email address.")
        return value