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
        "/var/task/SK",
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


def create_app() -> Flask:
    return app


if __name__ == "__main__":
    app.run(debug=True)
