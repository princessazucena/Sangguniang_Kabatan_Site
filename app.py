"""
Scholarship website — Flask entry point.

The public area handles sign-up / log-in and shows announcements.
Students upload their documents; admins review and verify them.
"""
import os
import bcrypt
from datetime import datetime, timezone, timedelta

from flask import Flask, redirect, url_for, session, request
from dotenv import load_dotenv
import logging

from routes.public import public_bp
from routes.student import student_bp
from routes.admin import admin_bp
from services.notifications import build_feed
from supabase_client import get_supabase


# Philippine time has no DST adjustments; offset is fixed at +08:00.
PH_TZ = timezone(timedelta(hours=8))


def _to_ph(value):
    """Coerce a value (str/datetime/None) into an aware PH-timezone datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PH_TZ)


def _ph_filter(value, fmt="%Y-%m-%d %H:%M"):
    """Jinja filter: render a UTC timestamp in Philippine time."""
    dt = _to_ph(value)
    return dt.strftime(fmt) if dt else ""


def _ph_date_filter(value, fmt="%Y-%m-%d"):
    """Jinja filter: render only the PH date for a UTC timestamp."""
    return _ph_filter(value, fmt)


load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

def get_template_search_paths():
    paths = []
    for candidate_root in [
        BASE_DIR,
        os.getcwd(),
        "/var/task",
        "/var/task/app",
        "/var/task/services/app",
    ]:
        if os.path.isdir(candidate_root):
            for root, dirs, files in os.walk(candidate_root):
                if any(x in root for x in [".venv", "__pycache__", "site-packages", ".git"]):
                    continue
                if "home.html" in files or "base.html" in files:
                    if root not in paths:
                        paths.append(root)
                    parent = os.path.dirname(root)
                    if parent not in paths:
                        paths.append(parent)
                if "templates" in dirs:
                    t_path = os.path.join(root, "templates")
                    if t_path not in paths:
                        paths.append(t_path)
    fallback = [
        os.path.join(BASE_DIR, "templates"),
        os.path.join(os.getcwd(), "templates"),
        "templates",
    ]
    for f in fallback:
        if f not in paths:
            paths.append(f)
    return paths

from jinja2 import FileSystemLoader, ChoiceLoader, DictLoader
try:
    from embedded_templates import EMBEDDED_TEMPLATES
except ImportError:
    EMBEDDED_TEMPLATES = {}

app.jinja_env.loader = ChoiceLoader([
    FileSystemLoader(get_template_search_paths()),
    DictLoader(EMBEDDED_TEMPLATES),
])

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload cap

# Harden the session cookie for production. SameSite=Lax stops most
# cross-site request forgery; Secure makes the browser refuse to send
# the cookie over plain HTTP; HttpOnly keeps it out of JavaScript so
# an XSS bug can't steal it.
app.config.update(
    SESSION_COOKIE_SECURE   = True,
    SESSION_COOKIE_HTTPONLY = True,
    SESSION_COOKIE_SAMESITE = "Lax",
)

# Trust the X-Forwarded-* headers from nginx so url_for() and
# request.is_secure return the right values when generating links
# (password-reset emails, redirects after login, etc.).
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Make timezone-aware formatters available in templates.
app.jinja_env.filters["ph"]      = _ph_filter
app.jinja_env.filters["ph_date"] = _ph_date_filter

app.register_blueprint(public_bp)
app.register_blueprint(student_bp, url_prefix="/student")
app.register_blueprint(admin_bp, url_prefix="/admin")

@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    logging.exception("Unhandled error on %s: %s", getattr(request, "path", "/"), e)
    return f"Internal Server Error: {e}", 500

@app.context_processor
def inject_notifications():
    """Make a notification feed available to every signed-in template."""
    role = session.get("role")
    if role not in ("student", "admin"):
        return {"notifications": []}
    try:
        feed = build_feed(
            get_supabase(),
            role=role,
            user_id=session.get("user_id"),
        )
    except Exception:
        feed = []
    return {"notifications": feed}

@app.route("/")
def index():
    # Logged-in users go straight to their dashboard.
    role = session.get("role")
    if role == "admin":
        return redirect(url_for("admin.dashboard"))
    if role == "student":
        return redirect(url_for("student.dashboard"))
    return redirect(url_for("public.home"))


def create_app() -> Flask:
    return app


if __name__ == "__main__":
    app.run(debug=True)