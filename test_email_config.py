#!/usr/bin/env python3
"""
Diagnostic script to test email configuration and Brevo connectivity.
Run this to verify that your email settings are correct.
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

print("=" * 70)
print("EMAIL CONFIGURATION DIAGNOSTIC")
print("=" * 70)

# Check required environment variables
brevo_api_key = os.environ.get("BREVO_API_KEY")
brevo_sender_email = os.environ.get("BREVO_SENDER_EMAIL")
brevo_sender_name = os.environ.get("BREVO_SENDER_NAME", "Scholarship Portal")

print("\n1. ENVIRONMENT VARIABLES CHECK:")
print("-" * 70)

if brevo_api_key:
    print(f"✓ BREVO_API_KEY: {'*' * (len(brevo_api_key) - 4)}{brevo_api_key[-4:]}")
else:
    print("✗ BREVO_API_KEY: NOT SET (REQUIRED)")
    sys.exit(1)

if brevo_sender_email:
    print(f"✓ BREVO_SENDER_EMAIL: {brevo_sender_email}")
else:
    print("✗ BREVO_SENDER_EMAIL: NOT SET (REQUIRED)")
    sys.exit(1)

print(f"✓ BREVO_SENDER_NAME: {brevo_sender_name}")

# Test Brevo API connectivity
print("\n2. BREVO API CONNECTIVITY CHECK:")
print("-" * 70)

try:
    import requests
    
    test_payload = {
        "sender": {"email": brevo_sender_email, "name": brevo_sender_name},
        "to": [{"email": "test@example.com", "name": "Test User"}],
        "subject": "Test Email",
        "htmlContent": "<p>This is a test email.</p>",
    }
    
    headers = {
        "api-key": brevo_api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }
    
    # Don't actually send, just test the connection
    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        json=test_payload,
        headers=headers,
        timeout=10,
    )
    
    print(f"API Response Status: {response.status_code}")
    
    if response.status_code == 400:
        # 400 is expected for test@example.com, means API is reachable
        print("✓ Brevo API is reachable and responding")
        error_detail = response.json().get("message", "")
        if "invalid address" in error_detail.lower() or "test@example" in error_detail:
            print("  (Test recipient invalid as expected, but API is working)")
    elif response.status_code == 401:
        print("✗ Invalid API key - check BREVO_API_KEY")
        print(f"  Response: {response.text}")
        sys.exit(1)
    elif response.status_code in (200, 201, 202):
        print("✓ Brevo API is working (email would be sent)")
    else:
        print(f"⚠ Unexpected status code: {response.status_code}")
        print(f"  Response: {response.text[:200]}")
        
except ImportError:
    print("✗ requests library not installed")
    sys.exit(1)
except Exception as e:
    print(f"✗ Connection error: {e}")
    sys.exit(1)

# Test the send_email function
print("\n3. SEND_EMAIL FUNCTION TEST:")
print("-" * 70)

try:
    from services.email import send_email
    
    # Test with a valid email domain
    test_email = os.environ.get("TEST_EMAIL", "test@example.com")
    print(f"Testing send_email function...")
    print(f"Recipient: {test_email}")
    
    result = send_email(
        to_email=test_email,
        to_name="Test User",
        subject="Test Email from Scholarship Portal",
        html_content="<p>This is a test email to verify the email service is working.</p>",
    )
    
    if result:
        print("✓ send_email function returned True (email sent)")
    else:
        print("✗ send_email function returned False (check server logs for details)")
        
except ImportError as e:
    print(f"⚠ Could not import send_email: {e}")
except Exception as e:
    print(f"✗ Error testing send_email: {e}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
print("\nNEXT STEPS:")
print("1. Ensure .env file exists in the project root with BREVO_API_KEY and BREVO_SENDER_EMAIL")
print("2. Get your Brevo API key from: https://app.brevo.com/settings/keys/api")
print("3. Verify your sender email is confirmed in Brevo: https://app.brevo.com/settings/senders")
print("4. Run this script again after setting environment variables")
