# Email Configuration Guide - Password Reset Fix

## Issue Summary
The reset password email functionality was not sending emails because:
1. **Missing environment variables** - Brevo API credentials not configured
2. **Code duplication** - Direct API calls instead of using centralized email service
3. **Limited error handling** - Minimal logging made debugging difficult

## What Was Fixed
✅ Refactored `_send_reset_email()` to use the centralized `services.email` module  
✅ Improved error handling and logging  
✅ Removed code duplication  
✅ Better user feedback when email sending fails  

## Required Setup: Brevo Configuration

### Step 1: Get Brevo Credentials
1. Go to https://app.brevo.com/settings/keys/api
2. Copy your **API Key** (or create a new one)
3. Go to https://app.brevo.com/settings/senders
4. Find or create a **verified sender email address**

### Step 2: Create `.env` File
Create a file named `.env` in the project root (`c:\Projects\SK\.env`):

```env
# Brevo Email Configuration (https://brevo.com)
BREVO_API_KEY=your_api_key_here
BREVO_SENDER_EMAIL=noreply@yourdomain.com
BREVO_SENDER_NAME=Scholarship Portal
```

### Step 3: Verify Configuration
Run the diagnostic script to test your setup:

```powershell
cd c:\Projects\SK
python test_email_config.py
```

You should see:
- ✓ BREVO_API_KEY detected
- ✓ BREVO_SENDER_EMAIL detected
- ✓ Brevo API is reachable

## Testing the Reset Password Flow

1. Go to `/forgot` page
2. Enter a test email address
3. Check server logs (Flask debug console) for:
   - ✓ "send_email skipped — missing Brevo config or recipient" = Missing API key
   - ✓ "Brevo send failed (401)" = Invalid API key
   - ✓ "Brevo send failed (400)" = Invalid sender email
   - ✓ No error = Email sent successfully

## Files Modified
- **routes/public.py** - Refactored email sending to use centralized service
- **test_email_config.py** - New diagnostic script

## Environment Variables Reference

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `BREVO_API_KEY` | Yes | `abc123def456...` | API key from Brevo dashboard |
| `BREVO_SENDER_EMAIL` | Yes | `noreply@example.com` | Verified sender email in Brevo |
| `BREVO_SENDER_NAME` | No | `Scholarship Portal` | Display name for emails (defaults to "Scholarship Portal") |

## Troubleshooting

### Email still not sending?
1. Check that API key is valid (no typos, spaces, or extra characters)
2. Verify sender email is **confirmed** in Brevo dashboard
3. Check Flask logs for specific error messages
4. Run `test_email_config.py` to diagnose

### "Missing Brevo config" error?
- Create the `.env` file with required variables
- Flask needs to be restarted after creating/modifying `.env`

### "Email provider returned 401"?
- API key is invalid or expired
- Get a new key from Brevo dashboard

### "Email provider returned 400"?
- Sender email is not verified in Brevo
- Check https://app.brevo.com/settings/senders

## Architecture Changes

**Before:** Direct HTTP calls to Brevo API in multiple places (duplication, poor error handling)

**After:** Centralized `services.email.send_email()` function provides:
- ✓ Consistent error handling and logging
- ✓ Single source of truth for email configuration
- ✓ Fire-and-forget pattern (doesn't break user flow if email fails)
- ✓ Automatic base64 encoding for attachments
- ✓ Better observability with structured logs
