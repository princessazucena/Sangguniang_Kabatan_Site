"""
Public routes: home (announcements), sign-up, log-in, log-out.
"""
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase

public_bp = Blueprint("public", __name__)


@public_bp.route("/home")
def home():
    sb = get_supabase()
    res = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return render_template("public/home.html", announcements=res.data or [])


@public_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not full_name or not email or len(password) < 6:
            flash("Please provide a name, email, and a password (6+ chars).", "error")
            return render_template("public/signup.html")

        sb = get_supabase()
        try:
            # Auto-confirm so the user can log in right away.
            created = sb.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name},
            })
            user = created.user
            sb.table("profiles").insert({
                "id": user.id,
                "full_name": full_name,
                "role": "student",
            }).execute()
        except Exception as exc:
            flash(f"Sign-up failed: {exc}", "error")
            return render_template("public/signup.html")

        flash("Account created. You can log in now.", "success")
        return redirect(url_for("public.login"))

    return render_template("public/signup.html")


@public_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        sb = get_supabase()
        try:
            auth_res = sb.auth.sign_in_with_password({
                "email": email, "password": password,
            })
        except Exception as exc:
            flash(f"Login failed: {exc}", "error")
            return render_template("public/login.html")

        user = auth_res.user
        if not user:
            flash("Invalid credentials.", "error")
            return render_template("public/login.html")

        prof = (
            sb.table("profiles")
            .select("id, full_name, role")
            .eq("id", user.id)
            .single()
            .execute()
        )
        if not prof.data:
            flash("Profile not found. Contact an admin.", "error")
            return render_template("public/login.html")

        session.clear()
        session["user_id"] = user.id
        session["full_name"] = prof.data["full_name"]
        session["role"] = prof.data["role"]

        if prof.data["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("student.dashboard"))

    return render_template("public/login.html")


@public_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.home"))
