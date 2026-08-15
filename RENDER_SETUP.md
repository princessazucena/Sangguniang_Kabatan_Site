# Render Deployment Guide

## Issue
Yung Render site ay:
1. Di naka-connect sa database (missing environment variables)
2. Showing old UI or data

## Solution

### 1. Configure Environment Variables sa Render

1. Go to Render Dashboard: https://dashboard.render.com/
2. Select your web service: **sangguniang-kabatan-site**
3. Go to **Environment** tab
4. Add these environment variables:

```
SUPABASE_URL=https://nksvgqxrjywxrbzbswug.supabase.co
SUPABASE_SECRET_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5rc3ZncXhyanl3eHJiemJzd3VnIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODU5MDc2MywiZXhwIjoyMDk0MTY2NzYzfQ.1poVL8F7uJ4utnmSFRz8UsSotvj-QvugifkEg424L1Q
SUPABASE_BUCKET=scholarship-files
FLASK_SECRET_KEY=change-me-to-a-long-random-string
BREVO_SENDER_EMAIL=ceaneazucena@gmail.com
BREVO_SENDER_NAME=Sangguniang Kabataan ng Bukal
BREVO_API_KEY=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
```

5. Click **Save Changes**

### 2. Force Redeploy

After setting environment variables:

1. Go to **Manual Deploy** section
2. Click **Clear build cache & deploy**
3. Wait for deployment to complete (5-10 minutes)

### 3. Verify Deployment

Check these URLs:
- Home: https://sangguniang-kabatan-site.onrender.com/home
- Login: https://sangguniang-kabatan-site.onrender.com/login
- Admin: https://sangguniang-kabatan-site.onrender.com/admin/dashboard

### 4. Check Build Configuration

Make sure Render is using:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 4 --threads 2 --timeout 60 application:application`
- **Python Version**: 3.12.5 (from runtime.txt)

## Troubleshooting

### If still showing old UI:

1. Check if latest code is deployed:
   - Go to **Deploys** tab
   - Check commit hash matches: `84ad70a` (latest)
   
2. Clear browser cache:
   - Press Ctrl+Shift+R (Windows)
   - Or Cmd+Shift+R (Mac)

3. Check Render logs:
   - Go to **Logs** tab
   - Look for errors like "SUPABASE_URL not set"
   - Look for "RuntimeError: SUPABASE_URL and SUPABASE_SECRET_KEY must be set"

### If database not connecting:

Check logs for:
```
RuntimeError: SUPABASE_URL and SUPABASE_SECRET_KEY must be set in .env
```

This means environment variables are missing. Go back to Step 1.

### If static files not loading:

Render should automatically serve static files from `/static` folder. If not:
1. Check Build Command includes: `pip install -r requirements.txt`
2. Make sure `static/` folder exists in repository
3. Check Flask config has: `static_folder="static"`

## Auto-Deploy from GitHub

To enable automatic deployments on push:

1. Go to **Settings** tab
2. Under **Build & Deploy**, enable **Auto-Deploy**
3. Select branch: **main**
4. Every push to main will trigger a new deployment

## Notes

- Render's free tier may spin down after inactivity
- First request after spin-down takes ~30-60 seconds
- Consider upgrading to paid tier for production use
- Environment variables are encrypted and not visible after saving
