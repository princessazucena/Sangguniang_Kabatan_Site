"""
Public routes: home (announcements), sign-up, email verification,
log-in, log-out.

Sign-up flow:
    1. /signup    -> create unconfirmed auth user, send OTP to email
    2. /verify    -> verify OTP, create profile row, log the user in
    3. /resend    -> resend the OTP if needed
"""
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase

public_bp = Blueprint("public", __name__)


# -----------------------------------------------------------------
# helpers
# -----------------------------------------------------------------
def _build_full_name(first: str, middle: str, last: str, suffix: str) -> str:
    parts = [p for p in [first, middle, last] if p]
    name = " ".join(parts)
    if suffix:
        name = f"{name} {suffix}"
    return name


# -----------------------------------------------------------------
# home
# -----------------------------------------------------------------
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


# -----------------------------------------------------------------
# sign up  (step 1: create auth user, send OTP)
# -----------------------------------------------------------------
@public_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        form = {
            "first_name":   (request.form.get("first_name") or "").strip(),
            "middle_name":  (request.form.get("middle_name") or "").strip(),
            "last_name":    (request.form.get("last_name") or "").strip(),
            "suffix":       (request.form.get("suffix") or "").strip(),
            "email":        (request.form.get("email") or "").strip().lower(),
            "facebook_url": (request.form.get("facebook_url") or "").strip(),
        }
        password    = request.form.get("password") or ""
        confirm_pw  = request.form.get("password_confirm") or ""

        # ---- validate ----
        if not form["first_name"] or not form["last_name"]:
            flash("First name and last name are required.", "error")
            return render_template("public/signup.html", form=form)
        if not form["email"]:
            flash("Email is required.", "error")
            return render_template("public/signup.html", form=form)
        if not form["facebook_url"].startswith(("http://", "https://")):
            flash("Please paste a valid Facebook URL (starting with https://).", "error")
            return render_template("public/signup.html", form=form)
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("public/signup.html", form=form)
        if password != confirm_pw:
            flash("Passwords do not match.", "error")
            return render_template("public/signup.html", form=form)

        full_name = _build_full_name(
            form["first_name"], form["middle_name"],
            form["last_name"], form["suffix"],
        )

        sb = get_supabase()

        # Stash signup details in the session so /verify can finish creating
        # the profile row after the OTP is confirmed.
        session["pending_signup"] = {
            "email":        form["email"],
            "full_name":    full_name,
            "first_name":   form["first_name"],
            "middle_name":  form["middle_name"] or None,
            "last_name":    form["last_name"],
            "suffix":       form["suffix"] or None,
            "facebook_url": form["facebook_url"],
        }

        try:
            # sign_up triggers Supabase to send the confirmation email
            # which we configure as a 6-digit token (see README).
            sb.auth.sign_up({
                "email": form["email"],
                "password": password,
                "options": {
                    "data": {"full_name": full_name},
                },
            })
        except Exception as exc:
            flash(f"Sign-up failed: {exc}", "error")
            return render_template("public/signup.html", form=form)

        flash("We sent a 6-digit code to your email. Enter it below.", "success")
        return redirect(url_for("public.verify", email=form["email"]))

    return render_template("public/signup.html", form={})


# -----------------------------------------------------------------
# verify  (step 2: confirm OTP, create profile, log in)
# -----------------------------------------------------------------
@public_bp.route("/verify", methods=["GET", "POST"])
def verify():
    email = (request.values.get("email") or "").strip().lower()
    if not email:
        flash("Missing email. Please sign up again.", "error")
        return redirect(url_for("public.signup"))

    if request.method == "POST":
        token = (request.form.get("token") or "").strip()
        if not token.isdigit() or len(token) != 6:
            flash("Enter the 6-digit code from the email.", "error")
            return render_template("public/verify.html", email=email)

        sb = get_supabase()
        verified_user = None
        try:
            res = sb.auth.verify_otp({
                "email": email,
                "token": token,
                "type":  "email",
            })
            verified_user = res.user
        except Exception as exc:
            # Common case: user clicked the magic link in the email which
            # already confirmed them, so the token is now "used". Check the
            # admin API and treat it as success if they're confirmed.
            try:
                listing = sb.auth.admin.list_users()
                users = getattr(listing, "users", None) or listing
                for u in users:
                    if (u.email or "").lower() == email and u.email_confirmed_at:
                        verified_user = u
                        break
            except Exception:
                pass
            if not verified_user:
                flash(
                    "That code is invalid or expired. "
                    "Tap 'Resend code' to get a new one — and use the code, not the link.",
                    "error",
                )
                return render_template("public/verify.html", email=email)

        if not verified_user:
            flash("Could not verify the code. Please try again.", "error")
            return render_template("public/verify.html", email=email)

        # Create the matching profiles row using the details we stashed.
        details = session.pop("pending_signup", {}) or {}
        sb.table("profiles").upsert({
            "id":           verified_user.id,
            "full_name":    details.get("full_name", email),
            "first_name":   details.get("first_name"),
            "middle_name":  details.get("middle_name"),
            "last_name":    details.get("last_name"),
            "suffix":       details.get("suffix"),
            "facebook_url": details.get("facebook_url"),
            "role":         "student",
        }).execute()

        flash("Email verified! You can log in now.", "success")
        return redirect(url_for("public.login"))

    return render_template("public/verify.html", email=email)


# -----------------------------------------------------------------
# resend OTP
# -----------------------------------------------------------------
@public_bp.route("/resend", methods=["POST"])
def resend_code():
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        return redirect(url_for("public.signup"))

    sb = get_supabase()
    try:
        sb.auth.resend({"type": "signup", "email": email})
        flash("New code sent. Check your email — use the 6-digit code, not the link.", "success")
    except Exception as exc:
        flash(f"Could not resend code: {exc}", "error")

    return redirect(url_for("public.verify", email=email))


# -----------------------------------------------------------------
# log in / log out
# -----------------------------------------------------------------
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
            msg = str(exc)
            if "Email not confirmed" in msg or "not confirmed" in msg.lower():
                flash("Please verify your email first. Check your inbox for the code.", "error")
                return redirect(url_for("public.verify", email=email))
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
        session["user_id"]   = user.id
        session["full_name"] = prof.data["full_name"]
        session["role"]      = prof.data["role"]

        if prof.data["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("student.dashboard"))

    return render_template("public/login.html")


@public_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.home"))
