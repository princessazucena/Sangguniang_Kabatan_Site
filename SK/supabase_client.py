"""
Thin wrapper around the Supabase Python client.

The secret (service-role) key is used server-side only, so all DB
calls in this app bypass RLS. Never expose this key to the browser.
"""
import os
from functools import lru_cache
from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    url = (
        os.environ.get("SUPABASE_URL")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    )
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be set in environment variables"
        )
    return create_client(url, key)


def get_bucket_name() -> str:
    return os.environ.get("SUPABASE_BUCKET", "scholarship-files")
