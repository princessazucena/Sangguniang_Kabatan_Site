# Password Reset Email Troubleshooting Guide

## Issue Reported
Password reset codes are being sent to the admin email (ceaneazucena@gmail.com) instead of to students.

## Investigation Findings

### 1. Code Analysis ✅
The code is **CORRECT**. The `send_email()` function properly sends emails TO the student's email address:
- `to_email`: Student's email (e.g., balalaandreajen@gmail.com)
- `from_email`: Admin email (ceaneazucena@gmail.com)

### 2. Brevo Configuration
**Account Details:**
- Plan: FREE
- Verified Sender: ceaneazucena@gmail.com
- Company: Laguna States Polytechnic University

**Possible Issues with Free Plan:**
1. Gmail might be treating emails as spam
2. Brevo free plan may have delivery restrictions
3. Students need to check their spam/junk folders

### 3. Email Screenshot Analysis
The screenshot showing "Re: Your Scholarship Portal password reset code" with "to me" suggests:
- **Andrea RECEIVED the email** (otherwise she couldn't reply)
- **She REPLIED to it** (that's why you see it in your inbox)
- The "Re:" prefix indicates it's a reply, not the original email

## How to Verify Email Delivery

### For Students:
1. **Check Spam/Junk Folder** - This is the most common issue!
2. **Check Promotions tab** (if using Gmail)
3. **Wait 5-10 minutes** - Email delivery can be delayed
4. **Add sender to contacts**: ceaneazucena@gmail.com

### For Admin:
1. **Check Brevo Dashboard**:
   - Go to: https://app.brevo.com/
   - Navigate to: "Campaigns" > "Transactional"
   - View email delivery logs

2. **Check Application Logs**:
   - After deployment, logs now show:
     - "Sending email: FROM '...' TO '...' SUBJECT '...'"
     - "Email sent successfully to {email} (Message ID: ...)"
   - Check AWS Elastic Beanstalk logs:
     ```
     eb logs
     ```

3. **Test Email Delivery**:
   Run the test script:
   ```bash
   python test_email_send.py
   ```
   Enter a test email address to verify delivery.

## Improvements Made

### 1. Enhanced Logging ✅
Added detailed logging in:
- `routes/public.py` - Password reset email preparation
- `services/email.py` - Email sending with Brevo API

Logs now show:
- Recipient email address
- Sender information
- Brevo Message ID (for tracking)
- Success/failure status

### 2. Email Body Improvement ✅
Added a footer note to password reset emails showing the intended recipient:
```
(This email should be received by {student_email})
```

This helps verify the email is being sent to the correct address.

## Common Issues & Solutions

### Issue 1: Emails Going to Spam
**Solution:**
- Ask students to check spam folder
- Mark as "Not Spam" if found there
- Add ceaneazucena@gmail.com to contacts

### Issue 2: Brevo Free Plan Limitations
**Solution:**
- Brevo free plan allows 300 emails/day
- If limit reached, upgrade to paid plan
- Check daily quota at: https://app.brevo.com/account/plan

### Issue 3: Gmail Blocking Emails
**Solution:**
- Gmail might block emails from unfamiliar senders
- Students should whitelist ceaneazucena@gmail.com
- Consider verifying domain (bukal.gov.ph) if available

### Issue 4: Wrong Email Address
**Solution:**
- Verify student's email in Supabase Auth
- Check profiles table for correct email
- Students can update email in their profile

## Testing Procedure

### Test 1: Send Password Reset
1. Go to: https://your-app.com/forgot
2. Enter a test student email
3. Check logs for: "Email sent successfully to {email}"
4. Check student inbox (and spam folder)
5. Verify reset code is received

### Test 2: Check Brevo Dashboard
1. Login to: https://app.brevo.com/
2. Go to: Statistics > Transactional
3. Check recent emails sent
4. Verify delivery status (sent, opened, bounced)

### Test 3: Verify Email Not Bouncing
1. In Brevo dashboard, check "Contacts"
2. Search for student email
3. If status is "Blacklisted" or "Bounced", the email is invalid
4. Ask student to provide correct email

## Recommended Next Steps

1. **Ask Andrea to check spam folder** ✅ Most likely solution!
2. **Check Brevo dashboard** for delivery confirmation
3. **Review EB logs** to verify email was sent
4. **Test with another student** to confirm it's not isolated
5. **Consider domain verification** for better deliverability

## Brevo Account Recommendations

### Immediate:
- ✅ Sender email verified (ceaneazucena@gmail.com)
- ⚠️ Consider verifying a domain for better deliverability
- ⚠️ Monitor daily sending quota (300 emails/day on free plan)

### Long-term:
- Consider upgrading to paid plan for:
  - Higher sending limits
  - Better deliverability
  - Priority support
- Set up SPF and DKIM records for domain
- Use a custom domain (e.g., @bukal.gov.ph) instead of Gmail

## Contact Information

**Brevo Support:**
- https://help.brevo.com/
- support@brevo.com

**Account Owner:**
- Email: ceaneazucena@gmail.com
- Account: Laguna States Polytechnic University
