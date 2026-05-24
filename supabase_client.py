"""
Thin wrapper around the Supabase Python client.

We intentionally DO NOT cache the client. The supabase-py client
mutates its own auth headers when ``auth.sign_in_with_password()``
is called, so a cached instance starts using the *user's* session
instead of the service-role key — which makes RLS apply to admin
operations. A fresh client per request keeps the secret key in
charge, so server-side calls always bypass RLS.
"""
import os
from supabase import create_client, Client


def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must be set in .env"
        )
    return create_client(url, key)


def get_bucket_name() -> str:
    return os.environ.get("SUPABASE_BUCKET", "scholarship-files")
