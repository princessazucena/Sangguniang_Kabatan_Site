"""
Public routes: home, sign-up, email verification, log-in, log-out.

We send our own 6-digit verification code via the Resend HTTP API
(independent from Supabase's built-in email confirmation).

Flow:
    /signup  -> create auth user (auto-confirmed in Supabase),
                create profile with email_verified=false + a fresh code,
                email the code via Resend.
    /verify  -> validate the code, set email_verified=true.
    /login   -> blocks accounts where email_verified=false.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

import requests
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase
from services.announcements import annotate

public_bp = Blueprint("public", __name__)

CODE_TTL_MINUTES = 15  # how long a verification code is valid


# -----------------------------------------------------------------
# helpers
# -----------------------------------------------------------------
def _build_full_name(first: str, middle: str, last: str, suffix: str) -> str:
    parts = [p for p in [first, middle, last] if p]
    name = " ".join(parts)
    if suffix:
        name = f"{name} {suffix}"
    return name


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _send_verification_email(to_email: str, full_name: str, code: str) -> None:
    """
    Send the 6-digit code via Brevo's HTTP API.
    Raises RuntimeError on failure.
    """
    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        raise RuntimeError("BREVO_API_KEY is not configured on the server.")

    sender_email = os.environ.get("BREVO_SENDER_EMAIL")
    sender_name  = os.environ.get(
        "BREVO_SENDER_NAME", "Sangguniang Kabataan ng Bukal",
    )
    if not sender_email:
        raise RuntimeError("BREVO_SENDER_EMAIL is not configured on the server.")

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color:#476a40;">Confirm your email</h2>
        <p>Hi {full_name or 'there'}, use the verification code below to
           finish creating your Scholarship Portal account:</p>
        <p style="font-size:28px; font-weight:bold; letter-spacing:8px;
                  padding:16px 20px; background:#f1f7ef; border-radius:8px;
                  display:inline-block; color:#476a40; font-family:monospace;">
            {code}
        </p>
        <p style="color:#6b7280; font-size:13px;">
            This code expires in {CODE_TTL_MINUTES} minutes.
            If you didn't request this, ignore this email.
        </p>
    </div>
    """

    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key":      api_key,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        json={
            "sender":      {"name": sender_name, "email": sender_email},
            "to":          [{"email": to_email, "name": full_name or to_email}],
            "subject":     "Your Scholarship Portal verification code",
            "htmlContent": html_body,
        },
        timeout=15,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Email provider returned {resp.status_code}: {resp.text}"
        )


def _set_new_code(sb, profile_id: str, email: str, full_name: str) -> None:
    """Generate a code, store it on the profile, and email it."""
    code = _generate_code()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)).isoformat()
    sb.table("profiles").update({
        "verification_code":            code,
        "verification_code_expires_at": expires_at,
        "email_verified":               False,
    }).eq("id", profile_id).execute()
    _send_verification_email(email, full_name, code)


# -----------------------------------------------------------------
# home
# -----------------------------------------------------------------
@public_bp.route("/home")
def home():
    # Logged-in users skip the public landing page and go straight
    # to their own area (announcements for students, dashboard for admins).
    role = session.get("role")
    if role == "student":
        return redirect(url_for("student.announcements"))
    if role == "admin":
        return redirect(url_for("admin.dashboard"))

    sb = get_supabase()
    res = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return render_template("public/home.html", announcements=annotate(res.data or []))


# -----------------------------------------------------------------
# sign up
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
        password   = request.form.get("password") or ""
        confirm_pw = request.form.get("password_confirm") or ""

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

        # Create the auth user with email_confirm=True so Supabase
        # doesn't try to send anything itself; we run the verification
        # ourselves via Resend.
        try:
            created = sb.auth.admin.create_user({
                "email": form["email"],
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name},
            })
            user = created.user
        except Exception as exc:
            flash(f"Sign-up failed: {exc}", "error")
            return render_template("public/signup.html", form=form)

        # Save the profile with email_verified=False.
        try:
            sb.table("profiles").upsert({
                "id":             user.id,
                "full_name":      full_name,
                "first_name":     form["first_name"],
                "middle_name":    form["middle_name"] or None,
                "last_name":      form["last_name"],
                "suffix":         form["suffix"] or None,
                "facebook_url":   form["facebook_url"],
                "role":           "student",
                "email_verified": False,
            }).execute()
        except Exception as exc:
            flash(f"Could not save profile: {exc}", "error")
            return render_template("public/signup.html", form=form)

        # Generate code + send the email.
        try:
            _set_new_code(sb, user.id, form["email"], full_name)
        except Exception as exc:
            flash(
                f"Account was created but we could not send the verification "
                f"email: {exc}. Tap 'Resend code' on the next page to try again.",
                "error",
            )
            return redirect(url_for("public.verify", email=form["email"]))

        flash("We sent a 6-digit code to your email. Enter it below.", "success")
        return redirect(url_for("public.verify", email=form["email"]))

    return render_template("public/signup.html", form={})


# -----------------------------------------------------------------
# verify
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

        # Find the auth user by email so we know which profile to check.
        try:
            users = sb.auth.admin.list_users()
            user_list = getattr(users, "users", None) or users
            user = next(
                (u for u in user_list if (u.email or "").lower() == email),
                None,
            )
        except Exception as exc:
            flash(f"Verification failed: {exc}", "error")
            return render_template("public/verify.html", email=email)

        if not user:
            flash("No account found for that email. Please sign up first.", "error")
            return render_template("public/verify.html", email=email)

        prof = (
            sb.table("profiles")
            .select("verification_code, verification_code_expires_at, email_verified, full_name")
            .eq("id", user.id)
            .single()
            .execute()
        ).data

        if not prof:
            flash("Profile not found. Please sign up again.", "error")
            return render_template("public/verify.html", email=email)

        if prof.get("email_verified"):
            flash("Email already verified. Please log in.", "success")
            return redirect(url_for("public.login"))

        if not prof.get("verification_code"):
            flash("No code on file. Tap 'Resend code' to get a fresh one.", "error")
            return render_template("public/verify.html", email=email)

        # Check expiry
        expires_str = prof.get("verification_code_expires_at")
        if expires_str:
            expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires:
                flash("That code has expired. Tap 'Resend code' to get a new one.", "error")
                return render_template("public/verify.html", email=email)

        if token != prof["verification_code"]:
            flash("Invalid code. Please try again.", "error")
            return render_template("public/verify.html", email=email)

        # All good -> mark verified and clear the code.
        sb.table("profiles").update({
            "email_verified":               True,
            "verification_code":            None,
            "verification_code_expires_at": None,
        }).eq("id", user.id).execute()

        flash("Email verified! You can log in now.", "success")
        return redirect(url_for("public.login"))

    return render_template("public/verify.html", email=email)


# -----------------------------------------------------------------
# resend code
# -----------------------------------------------------------------
@public_bp.route("/resend", methods=["POST"])
def resend_code():
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        return redirect(url_for("public.signup"))

    sb = get_supabase()
    try:
        users = sb.auth.admin.list_users()
        user_list = getattr(users, "users", None) or users
        user = next(
            (u for u in user_list if (u.email or "").lower() == email),
            None,
        )
        if not user:
            flash("No account found for that email.", "error")
            return redirect(url_for("public.signup"))

        prof = (
            sb.table("profiles").select("full_name, email_verified")
            .eq("id", user.id).single().execute()
        ).data
        if prof and prof.get("email_verified"):
            flash("Already verified — please log in.", "success")
            return redirect(url_for("public.login"))

        _set_new_code(sb, user.id, email, (prof or {}).get("full_name", ""))
        flash("New code sent. Check your email.", "success")
    except Exception as exc:
        flash(f"Could not resend code: {exc}", "error")

    return redirect(url_for("public.verify", email=email))


# -----------------------------------------------------------------
# log in / log out
# -----------------------------------------------------------------
@public_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = (request.values.get("next") or "").strip()

    def _safe_next(target: str) -> str | None:
        # Only allow same-site relative URLs.
        if target and target.startswith("/") and not target.startswith("//"):
            return target
        return None

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
            return render_template("public/login.html", next=next_url)

        user = auth_res.user
        if not user:
            flash("Invalid credentials.", "error")
            return render_template("public/login.html", next=next_url)

        prof = (
            sb.table("profiles")
            .select("id, full_name, role, email_verified")
            .eq("id", user.id)
            .single()
            .execute()
        )
        if not prof.data:
            flash("Profile not found. Contact an admin.", "error")
            return render_template("public/login.html", next=next_url)

        # Block login if email is not verified yet.
        if not prof.data.get("email_verified"):
            flash("Please verify your email before logging in.", "error")
            return redirect(url_for("public.verify", email=email))

        session.clear()
        session["user_id"]   = user.id
        session["full_name"] = prof.data["full_name"]
        session["role"]      = prof.data["role"]

        safe = _safe_next(next_url)
        if safe:
            return redirect(safe)
        if prof.data["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("student.dashboard"))

    return render_template("public/login.html", next=next_url)


@public_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.home"))
