"""
Scholarship website — Flask entry point.

The public area handles sign-up / log-in and shows announcements.
Students upload their documents; admins review and verify them.
"""
import os
from datetime import datetime, timezone, timedelta

from flask import Flask, redirect, url_for, session
from dotenv import load_dotenv

from routes.public import public_bp
from routes.student import student_bp
from routes.admin import admin_bp


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


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload cap

    # Make timezone-aware formatters available in templates.
    app.jinja_env.filters["ph"]      = _ph_filter
    app.jinja_env.filters["ph_date"] = _ph_date_filter

    app.register_blueprint(public_bp)
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.route("/")
    def index():
        # Logged-in users go straight to their dashboard.
        role = session.get("role")
        if role == "admin":
            return redirect(url_for("admin.dashboard"))
        if role == "student":
            return redirect(url_for("student.dashboard"))
        return redirect(url_for("public.home"))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
