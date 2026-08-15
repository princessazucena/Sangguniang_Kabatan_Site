from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase
from datetime import datetime, timezone

sb = get_supabase()

# Get Celine's application
celine_id = "a5d9495a-9529-4a55-a449-bb6f667f8731"
app = sb.table('applications').select('*').eq('student_id', celine_id).execute().data[0]

print("Application Details:")
print(f"  ID: {app['id']}")
print(f"  Status: {app['status']}")
print(f"  Registration ID: {app['registration_id']}")
print()

# Get the registration event
reg = sb.table('announcements').select('*').eq('id', app['registration_id']).execute().data[0]

print("Registration Event:")
print(f"  Title: {reg['title']}")
print(f"  Start: {reg['start_at']}")
print(f"  End: {reg['end_at']}")
print()

# Check schedule
now = datetime.now(timezone.utc)
start = datetime.fromisoformat(reg['start_at'].replace('Z', '+00:00'))
end = datetime.fromisoformat(reg['end_at'].replace('Z', '+00:00'))

print("Schedule Check:")
print(f"  Current time: {now}")
print(f"  Start time: {start}")
print(f"  End time: {end}")
print(f"  Is open: {start <= now <= end}")
print()

# Check upload permission logic
can_upload = app['status'] in ('pending', 'rejected')
print(f"Can upload (status check): {can_upload}")
print(f"  Reason: status is '{app['status']}' which is {'in' if can_upload else 'NOT in'} (pending, rejected)")
