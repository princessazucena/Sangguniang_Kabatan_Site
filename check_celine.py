from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase

sb = get_supabase()

# Check for Celine Cortez
result = sb.table('profiles').select('*').or_('first_name.ilike.%celine%,last_name.ilike.%cortez%').execute()

print(f'Found {len(result.data)} profiles:')
for p in result.data:
    print(f"  - ID: {p.get('id')} ({p.get('first_name')} {p.get('last_name')}) - role: {p.get('role')}")
    if p.get('role') == 'student':
        # Check applications
        apps = sb.table('applications').select('*').eq('student_id', p.get('id')).execute()
        print(f"    Applications: {len(apps.data)}")
        for app in apps.data:
            print(f"      - ID: {app.get('id')}, Status: {app.get('status')}, Registration: {app.get('registration_id')}")
