# How to Update Brevo API Key in AWS

## Problem
The Brevo API key in AWS Elastic Beanstalk is outdated/invalid, causing password reset emails to fail.

## Solution
Update the BREVO_API_KEY environment variable in AWS with the correct key from your Brevo dashboard.

## Steps:

### 1. Get the Correct API Key from Brevo
1. Go to: https://app.brevo.com/settings/keys/api
2. Click on the `EB_DELACRUZ` key (the one that never expires)
3. Click "Copy" or reveal the full key
4. The key should look like: `xkeysib-XXXXXXXXXXXXXXXX-YYYYYYYYYYYYYY`

### 2. Update AWS Environment Variable

Run this command (replace `YOUR_NEW_API_KEY_HERE` with the actual key from step 1):

```cmd
.venv\Scripts\eb.exe setenv BREVO_API_KEY=YOUR_NEW_API_KEY_HERE
```

**Example:**
```cmd
.venv\Scripts\eb.exe setenv BREVO_API_KEY=xkeysib-abc123def456-xyz789
```

### 3. Verify the Update

Check if the new key is set:
```cmd
.venv\Scripts\eb.exe printenv
```

You should see the new BREVO_API_KEY value.

### 4. Test Password Reset

1. Go to your website: https://your-site.com/forgot
2. Enter a test email address
3. Check if the email is received
4. Check Brevo dashboard logs: https://app.brevo.com/transactional/email/statistics

## Alternative: Update via AWS Console

If the EB CLI method doesn't work:

1. Go to: https://console.aws.amazon.com/elasticbeanstalk/
2. Click on your application
3. Click on "Configuration" in the left sidebar
4. Find "Software" section and click "Edit"
5. Scroll to "Environment properties"
6. Find `BREVO_API_KEY` and update its value
7. Click "Apply"
8. Wait for the environment to update (~2-3 minutes)

## Verification

After updating, check the Brevo dashboard:
- Go to: https://app.brevo.com/transactional/email/statistics
- Try sending a password reset email
- The email should appear in the logs immediately

## Current Key Info

**Old key in AWS:** `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`

This key is likely expired or invalid.

**Keys in Brevo Dashboard:**
- `sk_site` - Expires May 24, 2027
- `EB_DELACRUZ` - Never expires ✅ (Use this one!)

## Need Help?

If you can't find the API key or need assistance, you can:
1. Generate a new API key in Brevo dashboard
2. Or regenerate the existing `EB_DELACRUZ` key
3. Then follow steps 2-4 above
