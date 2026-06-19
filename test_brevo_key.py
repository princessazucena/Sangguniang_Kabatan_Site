"""
Test if the current Brevo API key in AWS is valid.
"""
import requests
import sys

# Get the key from AWS environment (same as production)
BREVO_API_KEY = "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"

print("="*60)
print("TESTING BREVO API KEY")
print("="*60)
print(f"API Key: {BREVO_API_KEY[:20]}... (truncated)")
print()

# Test 1: Check account info
print("Test 1: Checking account info...")
try:
    response = requests.get(
        "https://api.brevo.com/v3/account",
        headers={"api-key": BREVO_API_KEY},
        timeout=10
    )
    if response.status_code == 200:
        account_info = response.json()
        print("✓ API Key is VALID!")
        print(f"  Email: {account_info.get('email')}")
        print(f"  Company: {account_info.get('companyName')}")
    elif response.status_code == 401:
        print("✗ API Key is INVALID or EXPIRED!")
        print(f"  Error: {response.json()}")
        sys.exit(1)
    else:
        print(f"✗ Unexpected status code: {response.status_code}")
        print(f"  Response: {response.text}")
        sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print()

# Test 2: Try to send a test email
print("Test 2: Attempting to send test email to ceaneazucena@gmail.com...")
payload = {
    "sender": {"email": "ceaneazucena@gmail.com", "name": "SK Bukal Test"},
    "to": [{"email": "ceaneazucena@gmail.com", "name": "Test User"}],
    "subject": "Test Email - Brevo API Key Verification",
    "htmlContent": "<p>This is a test email to verify the Brevo API key is working.</p>"
}

try:
    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        json=payload,
        headers={
            "api-key": BREVO_API_KEY,
            "accept": "application/json",
            "content-type": "application/json"
        },
        timeout=10
    )
    if response.status_code in (200, 201, 202):
        print("✓ Test email sent successfully!")
        result = response.json()
        print(f"  Message ID: {result.get('messageId')}")
        print()
        print("CHECK YOUR EMAIL (ceaneazucena@gmail.com) for the test message!")
        print("If you receive it, the API key is working correctly.")
    else:
        print(f"✗ Failed to send email: {response.status_code}")
        print(f"  Response: {response.text}")
        sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print()
print("="*60)
print("CONCLUSION:")
print("="*60)
print("If you received the test email, the Brevo API key is working!")
print("The issue might be elsewhere (check application logs).")
print()
print("If you DID NOT receive the email:")
print("1. Check your spam folder")
print("2. Check Brevo dashboard for delivery status")
print("3. The API key might have sending restrictions")
print("="*60)
