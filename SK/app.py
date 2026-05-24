"""
Scholarship website — Flask entry point.

The public area handles sign-up / log-in and shows announcements.
Students upload their documents; admins review and verify them.
"""
import os
from flask import Flask, redirect, url_for, session
from dotenv import load_dotenv

from routes.public import public_bp
from routes.student import student_bp
from routes.admin import admin_bp


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload cap

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
