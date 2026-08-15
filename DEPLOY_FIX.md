# Database Connection Fix

## Issue
The Elastic Beanstalk environment variables are not configured, causing database connection failures.

## Solution
Set environment variables in AWS Elastic Beanstalk console:

### Steps:
1. Go to AWS Elastic Beanstalk Console
2. Select application: **scholarship-portal**
3. Select environment: **scholarship-env**
4. Go to **Configuration** → **Software** → **Edit**
5. Add these environment properties:

```
SUPABASE_URL=https://nksvgqxrjywxrbzbswug.supabase.co
SUPABASE_SECRET_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5rc3ZncXhyanl3eHJiemJzd3VnIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODU5MDc2MywiZXhwIjoyMDk0MTY2NzYzfQ.1poVL8F7uJ4utnmSFRz8UsSotvj-QvugifkEg424L1Q
SUPABASE_BUCKET=scholarship-files
FLASK_SECRET_KEY=change-me-to-a-long-random-string
BREVO_SENDER_EMAIL=ceaneazucena@gmail.com
BREVO_SENDER_NAME=Sangguniang Kabataan ng Bukal
BREVO_API_KEY=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
```

6. Click **Apply**
7. Wait for environment to update (takes ~5 minutes)

## Alternative: Fix AWS Credentials
Your AWS credentials have expired. To fix:

```powershell
# Reconfigure AWS CLI credentials
aws configure
```

Then enter:
- AWS Access Key ID
- AWS Secret Access Key  
- Default region: ap-southeast-1
- Default output format: json

After that, you can deploy with:
```powershell
.venv\Scripts\eb.exe deploy
```
