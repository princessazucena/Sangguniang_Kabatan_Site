from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase
from datetime import datetime, timezone

sb = get_supabase()

# Check current events (registration announcements)
events = sb.table('announcements').select('*').eq('category', 'registration').order('created_at', desc=True).limit(3).execute()

print(f'Found {len(events.data)} registration events:')
print()

for event in events.data:
    print(f"Event ID: {event.get('id')}")
    print(f"  Title: {event.get('title')}")
    print(f"  Start: {event.get('start_at')}")
    print(f"  End: {event.get('end_at')}")
    
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(event.get('start_at').replace('Z', '+00:00')) if event.get('start_at') else None
    end = datetime.fromisoformat(event.get('end_at').replace('Z', '+00:00')) if event.get('end_at') else None
    
    is_open = False
    if start and end:
        is_open = start <= now <= end
    elif start:
        is_open = now >= start
        
    print(f"  Status: {'OPEN' if is_open else 'CLOSED'}")
    print(f"  Current time: {now.isoformat()}")
    
    # Check applications for this event
    apps = sb.table('applications').select('id, student_id, status').eq('registration_id', event.get('id')).execute()
    print(f"  Applications: {len(apps.data)}")
    print()
