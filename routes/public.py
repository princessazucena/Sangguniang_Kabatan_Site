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
import re
import secrets
import logging
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase
from services.announcements import annotate, filter_visible
from services.names import title_name, build_full_name
from services.email import send_email
from services import psgc

public_bp = Blueprint("public", __name__)

CODE_TTL_MINUTES = 15  # how long a verification code is valid

# Password rules: at least 8 chars, with one digit and one special character.
PASSWORD_MIN_LENGTH = 8
PASSWORD_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")


def _validate_password(password: str) -> str | None:
    """Return an error message if the password is weak, else ``None``."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if not any(ch.isdigit() for ch in password):
        return "Password must contain at least one number."
    if not PASSWORD_SPECIAL_RE.search(password):
        return "Password must contain at least one special character (e.g. ! @ # $ %)."
    return None


# -----------------------------------------------------------------
# helpers
# -----------------------------------------------------------------
def _build_full_name(first: str, middle: str, last: str, suffix: str) -> str:
    return build_full_name(first, middle, last, suffix)


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
# PSGC lookup proxy (region / province / city-municipality / barangay)
# -----------------------------------------------------------------
from flask import jsonify


@public_bp.route("/api/psgc/regions")
def psgc_regions():
    return jsonify(psgc.list_regions())


@public_bp.route("/api/psgc/regions/<region_code>/provinces")
def psgc_provinces(region_code: str):
    return jsonify(psgc.list_provinces(region_code))


@public_bp.route("/api/psgc/cities-municipalities")
def psgc_cities():
    region_code   = (request.args.get("region") or "").strip()
    province_code = (request.args.get("province") or "").strip() or None
    return jsonify(psgc.list_cities_municipalities(region_code, province_code))


@public_bp.route("/api/psgc/cities-municipalities/<code>/barangays")
def psgc_barangays(code: str):
    return jsonify(psgc.list_barangays(code))


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
        .eq("notify_landing", True)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return render_template("public/home.html", announcements=annotate(filter_visible(res.data or [])))


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
            "address_house_no": (request.form.get("address_house_no") or "").strip(),
            "address_street":   (request.form.get("address_street") or "").strip(),
            "address_purok":    (request.form.get("address_purok") or "").strip(),
            "address_region":   (request.form.get("address_region") or "").strip(),
            "address_province": (request.form.get("address_province") or "").strip(),
            "address_city":     (request.form.get("address_city") or "").strip(),
            "address_barangay": (request.form.get("address_barangay") or "").strip(),
            "address_zip":      (request.form.get("address_zip") or "").strip(),
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
        # Address: house no., purok, barangay, city, and province are required.
        # Street and ZIP are optional.
        required_addr = {
            "address_house_no": "House / Lot / Block number",
            "address_purok":    "Purok / Sitio",
            "address_region":   "Region",
            "address_city":     "City / Municipality",
            "address_barangay": "Barangay",
        }
        for field, label in required_addr.items():
            if not form[field]:
                flash(f"{label} is required.", "error")
                return render_template("public/signup.html", form=form)
        # Province is required for everywhere except NCR (which has no
        # provinces in PSGC).
        if "ncr" not in form["address_region"].lower() and not form["address_province"]:
            flash("Province is required.", "error")
            return render_template("public/signup.html", form=form)
        if form["address_zip"] and not (form["address_zip"].isdigit() and len(form["address_zip"]) == 4):
            flash("ZIP code must be 4 digits.", "error")
            return render_template("public/signup.html", form=form)
        pw_err = _validate_password(password)
        if pw_err:
            flash(pw_err, "error")
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
                "first_name":     title_name(form["first_name"]),
                "middle_name":    title_name(form["middle_name"]) or None,
                "last_name":      title_name(form["last_name"]),
                "suffix":         title_name(form["suffix"]) or None,
                "facebook_url":   form["facebook_url"],
                "address_house_no": form["address_house_no"] or None,
                "address_street":   form["address_street"] or None,
                "address_purok":    form["address_purok"] or None,
                "address_region":   form["address_region"] or None,
                "address_province": form["address_province"] or None,
                "address_city":     form["address_city"] or None,
                "address_barangay": form["address_barangay"] or None,
                "address_zip":      form["address_zip"] or None,
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
LOGIN_MAX_ATTEMPTS  = 5      # wrong passwords allowed before we lock
LOGIN_LOCKOUT_SECONDS = 60   # how long the lock lasts


def _profile_by_email(sb, email: str) -> dict | None:
    """Look up the profile row for an email, or ``None``."""
    try:
        users = sb.auth.admin.list_users()
        user_list = getattr(users, "users", None) or users
        user = next(
            (u for u in user_list if (u.email or "").lower() == email),
            None,
        )
    except Exception:
        return None
    if not user:
        return None
    res = (
        sb.table("profiles")
        .select("id, failed_login_attempts, lockout_until")
        .eq("id", user.id)
        .single()
        .execute()
    )
    return res.data


def _lockout_remaining_seconds(prof: dict | None) -> int:
    """Return seconds left in the lockout window, or 0 if not locked."""
    if not prof:
        return 0
    iso = prof.get("lockout_until")
    if not iso:
        return 0
    try:
        until = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return 0
    delta = (until - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(delta + 0.999))  # round up so 0.1s still shows as 1


@public_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = (request.values.get("next") or "").strip()

    def _safe_next(target: str) -> str | None:
        # Only allow same-site relative URLs.
        if target and target.startswith("/") and not target.startswith("//"):
            return target
        return None

    # Pre-check: if the email on the form (or already in the URL) is locked,
    # surface the remaining time so the countdown survives a page refresh.
    pre_email = (request.values.get("email") or "").strip().lower()
    pre_lock = 0
    if pre_email:
        sb_pre = get_supabase()
        pre_lock = _lockout_remaining_seconds(_profile_by_email(sb_pre, pre_email))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        sb = get_supabase()

        # If the account is currently locked, refuse before even hitting auth.
        prof_row = _profile_by_email(sb, email) if email else None
        remaining = _lockout_remaining_seconds(prof_row)
        if remaining > 0:
            flash(
                f"Too many failed attempts. Please try again in {remaining} second"
                f"{'s' if remaining != 1 else ''}.",
                "error",
            )
            return render_template(
                "public/login.html",
                next=next_url,
                lockout_seconds=remaining,
                lockout_email=email,
            )

        try:
            auth_res = sb.auth.sign_in_with_password({
                "email": email, "password": password,
            })
        except Exception as exc:
            # Wrong password (or any auth error). Bump the counter and
            # lock the account once we've crossed the threshold.
            remaining = _register_failed_login(sb, prof_row)
            if remaining > 0:
                flash(
                    f"Too many failed attempts. Please try again in {remaining} second"
                    f"{'s' if remaining != 1 else ''}.",
                    "error",
                )
            else:
                flash(f"Login failed: {exc}", "error")
            return render_template(
                "public/login.html",
                next=next_url,
                lockout_seconds=remaining,
                lockout_email=email,
            )

        user = auth_res.user
        if not user:
            remaining = _register_failed_login(sb, prof_row)
            if remaining > 0:
                flash(
                    f"Too many failed attempts. Please try again in {remaining} second"
                    f"{'s' if remaining != 1 else ''}.",
                    "error",
                )
            else:
                flash("Invalid credentials.", "error")
            return render_template(
                "public/login.html",
                next=next_url,
                lockout_seconds=remaining,
                lockout_email=email,
            )

        prof = (
            sb.table("profiles")
            .select("id, full_name, first_name, middle_name, last_name, "
                    "suffix, role, email_verified, is_active")
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

        # Block deactivated accounts (admin can deactivate from user mgmt).
        # ``is_active`` defaults to True; treat missing values as active so
        # legacy rows still work before the migration runs.
        if prof.data.get("is_active") is False:
            flash("Your account is deactivated. Please contact the admin.", "error")
            return render_template("public/login.html", next=next_url)

        # Successful login -> reset the throttle counter.
        try:
            sb.table("profiles").update({
                "failed_login_attempts": 0,
                "lockout_until":         None,
            }).eq("id", user.id).execute()
        except Exception:
            pass

        # Retroactively normalize names to Title Case so historic rows
        # like "TYARISSE ANN cortez BANAY" or "ken justin carreon" show
        # up cleanly across the portal (joiner sheet, certificates, admin
        # views). We only push an update when the stored values differ.
        try:
            current_first  = prof.data.get("first_name")  or ""
            current_middle = prof.data.get("middle_name") or ""
            current_last   = prof.data.get("last_name")   or ""
            current_suffix = prof.data.get("suffix")      or ""
            current_full   = prof.data.get("full_name")   or ""

            new_first  = title_name(current_first)
            new_middle = title_name(current_middle)
            new_last   = title_name(current_last)
            new_suffix = title_name(current_suffix)
            if new_first or new_last:
                new_full = build_full_name(
                    new_first, new_middle, new_last, new_suffix,
                )
            else:
                # Fall back to title-casing whatever is in full_name when
                # the per-part columns are blank (older legacy rows).
                new_full = title_name(current_full)

            updates: dict = {}
            if new_first  != current_first:  updates["first_name"]  = new_first
            if new_middle != current_middle: updates["middle_name"] = new_middle or None
            if new_last   != current_last:   updates["last_name"]   = new_last
            if new_suffix != current_suffix: updates["suffix"]      = new_suffix or None
            if new_full   != current_full:   updates["full_name"]   = new_full

            if updates:
                sb.table("profiles").update(updates).eq("id", user.id).execute()
                # Reflect the change in the in-memory record we hand to
                # the session below.
                prof.data["full_name"] = new_full
        except Exception:
            # Cosmetic only — don't block login if the rewrite fails.
            pass

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

    return render_template(
        "public/login.html",
        next=next_url,
        lockout_seconds=pre_lock,
        lockout_email=pre_email,
    )


def _register_failed_login(sb, prof_row: dict | None) -> int:
    """
    Bump ``failed_login_attempts`` and start the lockout if the threshold
    has been hit. Returns the seconds left in the lockout window
    (``0`` if not locked).
    """
    if not prof_row or not prof_row.get("id"):
        return 0
    attempts = (prof_row.get("failed_login_attempts") or 0) + 1
    update = {"failed_login_attempts": attempts}
    remaining = 0
    if attempts >= LOGIN_MAX_ATTEMPTS:
        until = datetime.now(timezone.utc) + timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
        update["lockout_until"] = until.isoformat()
        update["failed_login_attempts"] = 0  # reset so the next lockout requires a fresh streak
        remaining = LOGIN_LOCKOUT_SECONDS
    try:
        sb.table("profiles").update(update).eq("id", prof_row["id"]).execute()
    except Exception:
        pass
    return remaining


@public_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.home"))


# -----------------------------------------------------------------
# forgot password
# -----------------------------------------------------------------
def _send_reset_email(to_email: str, full_name: str, code: str) -> bool:
    """Send the password-reset OTP using the centralized email service.
    
    Returns True if sent successfully, False otherwise.
    Errors are logged but not raised — this allows the password reset
    flow to continue even if email temporarily fails.
    """
    import logging
    log = logging.getLogger(__name__)
    
    log.info(f"Preparing to send password reset email to: {to_email} (name: {full_name})")
    
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color:#476a40;">Reset your password</h2>
        <p>Hi {full_name or 'there'}, use the verification code below to
           reset your Scholarship Portal password:</p>
        <p style="font-size:28px; font-weight:bold; letter-spacing:8px;
                  padding:16px 20px; background:#f1f7ef; border-radius:8px;
                  display:inline-block; color:#476a40; font-family:monospace;">
            {code}
        </p>
        <p style="color:#6b7280; font-size:13px;">
            This code expires in {CODE_TTL_MINUTES} minutes. If you didn't
            request a reset, you can safely ignore this email.
        </p>
        <p style="color:#94a3b8; font-size:11px; margin-top:16px;">
            (This email should be received by {to_email})
        </p>
    </div>
    """

    success = send_email(
        to_email=to_email,
        to_name=full_name or to_email,
        subject="Your Scholarship Portal password reset code",
        html_content=html_body,
    )
    
    if success:
        log.info(f"Successfully sent password reset email to {to_email}")
    else:
        log.error(f"Failed to send password reset email to {to_email}")
    
    return success


def _store_reset_code(sb, profile_id: str) -> str:
    """Generate a fresh 6-digit reset code, persist it, return it."""
    code = _generate_code()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)).isoformat()
    sb.table("profiles").update({
        "verification_code":            code,
        "verification_code_expires_at": expires_at,
    }).eq("id", profile_id).execute()
    return code


def _find_user_by_email(sb, email: str):
    """Look up an auth user by lowercased email. Returns the user or None.
    
    Uses pagination to fetch all users since list_users() defaults to 50 per page.
    """
    import logging
    log = logging.getLogger(__name__)
    
    log.info(f"[FIND USER] START: Searching for email: {email}")
    try:
        page = 1
        found_users = 0
        while True:
            log.info(f"[FIND USER] Fetching page {page}...")
            try:
                users_response = sb.auth.admin.list_users(page=page, per_page=100)
            except TypeError:
                # Older client signature: returns everything in one call
                log.info(f"[FIND USER] Using non-paginated API")
                users_response = sb.auth.admin.list_users()
            
            user_list = getattr(users_response, "users", None) or users_response
            
            if not user_list:
                log.info(f"[FIND USER] Page {page} is empty, stopping pagination")
                break
            
            found_users += len(user_list) if user_list else 0
            log.info(f"[FIND USER] Got {len(user_list) if user_list else 0} users on page {page}")
            
            for u in user_list:
                user_email = (getattr(u, "email", None) or "").lower().strip()
                if user_email == email:
                    log.info(f"[FIND USER] FOUND user after checking {found_users} total users: {getattr(u, 'id', '?')} with email: {user_email}")
                    return u
            
            # If we got fewer than 100, this was the last page
            if len(user_list) < 100:
                break
            page += 1
        
        log.info(f"[FIND USER] User NOT FOUND after checking {found_users} total users for email: {email}")
        return None
    except Exception as e:
        log.error(f"[FIND USER] ERROR: {type(e).__name__}: {str(e)}", exc_info=True)
        return None


@public_bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    """Step 1 — student enters email, we send a reset code."""
    import logging
    log = logging.getLogger(__name__)
    
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        log.info(f"[FORGOT PASSWORD] Request received for email: {email}")
        
        if not email:
            flash("Please enter your email.", "error")
            return render_template("public/forgot_password.html", email="")

        sb = get_supabase()
        log.info(f"[FORGOT PASSWORD] Looking up user for email: {email}")
        user = _find_user_by_email(sb, email)
        
        if user:
            log.info(f"[FORGOT PASSWORD] User found: {user.id}")
        else:
            log.info(f"[FORGOT PASSWORD] User not found for email: {email}")
        
        # Don't leak whether the email exists — always pretend we sent it.
        if user:
            try:
                log.info(f"[FORGOT PASSWORD] Fetching profile for user: {user.id}")
                prof = (
                    sb.table("profiles")
                    .select("full_name, email_verified")
                    .eq("id", user.id)
                    .single()
                    .execute()
                ).data or {}
                log.info(f"[FORGOT PASSWORD] Profile fetched: {prof.get('full_name')}")
                
                log.info(f"[FORGOT PASSWORD] Storing reset code for user: {user.id}")
                code = _store_reset_code(sb, user.id)
                log.info(f"[FORGOT PASSWORD] Reset code stored: {code}")
                
                log.info(f"[FORGOT PASSWORD] Sending reset email to: {email}")
                success = _send_reset_email(email, prof.get("full_name") or "", code)
                log.info(f"[FORGOT PASSWORD] Email send result: {success}")
                
                if not success:
                    log.warning(f"[FORGOT PASSWORD] Email sending failed for: {email}")
                    flash("Email sending encountered an issue, but your reset code is ready. Check spam folder.", "warning")
                else:
                    log.info(f"[FORGOT PASSWORD] Email sent successfully to: {email}")
            except Exception as exc:
                log.error(f"[FORGOT PASSWORD] Exception occurred for {email}: {exc}", exc_info=True)
                flash("There was an issue sending your reset code. Please try again in a moment.", "error")
                return render_template("public/forgot_password.html", email=email)

        log.info(f"[FORGOT PASSWORD] Redirecting to reset page for email: {email}")
        flash("If that email is registered, we sent a reset code. Check your inbox.", "success")
        return redirect(url_for("public.reset_password", email=email))

    return render_template("public/forgot_password.html", email="")


@public_bp.route("/reset", methods=["GET", "POST"])
def reset_password():
    """Step 2 — student enters the OTP and a new password."""
    email = (request.values.get("email") or "").strip().lower()
    if not email:
        return redirect(url_for("public.forgot_password"))

    if request.method == "POST":
        token       = (request.form.get("token") or "").strip()
        new_pw      = request.form.get("password") or ""
        confirm_pw  = request.form.get("password_confirm") or ""

        if not token.isdigit() or len(token) != 6:
            flash("Enter the 6-digit code from the email.", "error")
            return render_template("public/reset_password.html", email=email)

        pw_err = _validate_password(new_pw)
        if pw_err:
            flash(pw_err, "error")
            return render_template("public/reset_password.html", email=email)
        if new_pw != confirm_pw:
            flash("Passwords do not match.", "error")
            return render_template("public/reset_password.html", email=email)

        sb = get_supabase()
        user = _find_user_by_email(sb, email)
        if not user:
            flash("Invalid or expired code.", "error")
            return render_template("public/reset_password.html", email=email)

        prof = (
            sb.table("profiles")
            .select("verification_code, verification_code_expires_at")
            .eq("id", user.id)
            .single()
            .execute()
        ).data or {}

        if not prof.get("verification_code"):
            flash("No code on file. Tap 'Resend code' to get a fresh one.", "error")
            return render_template("public/reset_password.html", email=email)

        expires_str = prof.get("verification_code_expires_at")
        if expires_str:
            expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires:
                flash("That code has expired. Tap 'Resend code' to get a new one.", "error")
                return render_template("public/reset_password.html", email=email)

        if token != prof["verification_code"]:
            flash("Invalid code. Please try again.", "error")
            return render_template("public/reset_password.html", email=email)

        # All checks passed — update the auth password and clear the code.
        try:
            sb.auth.admin.update_user_by_id(user.id, {"password": new_pw})
        except Exception as exc:
            flash(f"Could not update your password: {exc}", "error")
            return render_template("public/reset_password.html", email=email)

        sb.table("profiles").update({
            "verification_code":            None,
            "verification_code_expires_at": None,
        }).eq("id", user.id).execute()

        flash("Password updated. Please log in with your new password.", "success")
        return redirect(url_for("public.login"))

    return render_template("public/reset_password.html", email=email)


@public_bp.route("/forgot/resend", methods=["POST"])
def resend_reset_code():
    """Re-send a reset OTP from the reset page."""
    import logging
    log = logging.getLogger(__name__)
    
    email = (request.form.get("email") or "").strip().lower()
    log.info(f"[RESEND CODE] Request received for email: {email}")
    
    if not email:
        log.warning(f"[RESEND CODE] No email provided, redirecting to forgot page")
        return redirect(url_for("public.forgot_password"))

    sb = get_supabase()
    log.info(f"[RESEND CODE] Looking up user for email: {email}")
    user = _find_user_by_email(sb, email)
    
    if user:
        log.info(f"[RESEND CODE] User found: {user.id}")
        try:
            prof = (
                sb.table("profiles")
                .select("full_name")
                .eq("id", user.id)
                .single()
                .execute()
            ).data or {}
            log.info(f"[RESEND CODE] Profile fetched: {prof.get('full_name')}")
            
            code = _store_reset_code(sb, user.id)
            log.info(f"[RESEND CODE] Reset code stored: {code}")
            
            log.info(f"[RESEND CODE] Sending reset email to: {email}")
            success = _send_reset_email(email, prof.get("full_name") or "", code)
            log.info(f"[RESEND CODE] Email send result: {success}")
            if success:
                flash("New code sent. Check your email.", "success")
            else:
                flash("Code generated but email sending failed. Check spam folder.", "warning")
        except Exception as exc:
            log.error(f"[RESEND CODE] Error: {exc}", exc_info=True)
            flash("Could not resend code. Please try again.", "error")
    else:
        log.warning(f"[RESEND CODE] User not found for email: {email}")
        flash("If that email is registered, we sent a new code.", "success")

    return redirect(url_for("public.reset_password", email=email))
