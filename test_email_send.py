"""
Test script to verify Brevo email sending configuration.
This will help diagnose why reset emails are not reaching students.
"""
import os
from dotenv import load_dotenv
import requests

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Scholarship Portal")

print("="*60)
print("BREVO EMAIL CONFIGURATION TEST")
print("="*60)
print(f"Sender Email: {BREVO_SENDER_EMAIL}")
print(f"Sender Name: {BREVO_SENDER_NAME}")
print(f"API Key: {BREVO_API_KEY[:10]}... (hidden)")
print()

# Check account info
print("Checking Brevo account status...")
try:
    response = requests.get(
        "https://api.brevo.com/v3/account",
        headers={"api-key": BREVO_API_KEY},
        timeout=10
    )
    if response.status_code == 200:
        account_info = response.json()
        print("✓ Account Info:")
        print(f"  Email: {account_info.get('email')}")
        print(f"  Company: {account_info.get('companyName', 'N/A')}")
        print(f"  Plan: {account_info.get('plan', [{}])[0].get('type', 'Unknown')}")
        
        # Check if there are any restrictions
        marketing_automation = account_info.get('marketingAutomation', {})
        print(f"  Marketing Automation: {marketing_automation.get('enabled', False)}")
    else:
        print(f"✗ Failed to get account info: {response.status_code}")
        print(f"  Response: {response.text}")
except Exception as e:
    print(f"✗ Error checking account: {e}")

print()

# Check senders list
print("Checking verified senders...")
try:
    response = requests.get(
        "https://api.brevo.com/v3/senders",
        headers={"api-key": BREVO_API_KEY},
        timeout=10
    )
    if response.status_code == 200:
        senders = response.json().get('senders', [])
        print(f"✓ Found {len(senders)} verified sender(s):")
        for sender in senders:
            print(f"  - {sender.get('name')} <{sender.get('email')}>")
            print(f"    Active: {sender.get('active', False)}")
    else:
        print(f"✗ Failed to get senders: {response.status_code}")
except Exception as e:
    print(f"✗ Error checking senders: {e}")

print()

# Test sending an email
test_recipient = input("Enter a test email address to send to (or press Enter to skip): ").strip()
if test_recipient:
    print(f"\nSending test email to {test_recipient}...")
    payload = {
        "sender": {"email": BREVO_SENDER_EMAIL, "name": BREVO_SENDER_NAME},
        "to": [{"email": test_recipient, "name": "Test Recipient"}],
        "subject": "Test Email from SK Scholarship Portal",
        "htmlContent": "<p>This is a test email to verify Brevo configuration.</p>"
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
            print(f"  Message ID: {response.json().get('messageId')}")
            print(f"\nIMPORTANT: Check if the email arrived at {test_recipient}")
            print("If it arrived at the SENDER email instead, your Brevo account")
            print("may be in sandbox/test mode or have domain restrictions.")
        else:
            print(f"✗ Failed to send test email: {response.status_code}")
            print(f"  Response: {response.text}")
    except Exception as e:
        print(f"✗ Error sending test email: {e}")
else:
    print("Skipping test email send.")

print()
print("="*60)
print("RECOMMENDATIONS:")
print("="*60)
print("1. Verify your Brevo account is NOT in sandbox/test mode")
print("2. Check https://app.brevo.com/settings/senders")
print("3. Ensure the sender email is verified")
print("4. Check for any sending restrictions or limits")
print("5. If using a free plan, there may be domain restrictions")
print("="*60)
