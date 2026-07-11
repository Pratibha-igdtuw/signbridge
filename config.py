"""
Configuration for the Secure Student Management System v3 Enhanced.
"""
import os

# FLASK_ENV controls whether hardcoded dev fallbacks are allowed.
# Set FLASK_ENV=production on any real/deployed server.
_ENV = os.environ.get("FLASK_ENV", "development")
_IS_PRODUCTION = _ENV == "production"

_DEV_SECRET_KEY = "change-me-in-production-7f3a9c1e"
_DEV_JWT_SECRET = "change-me-jwt-2b8d4f6a"


def _require_env(var_name, dev_fallback):
    value = os.environ.get(var_name)
    if value:
        return value
    if _IS_PRODUCTION:
        raise RuntimeError(
            f"{var_name} is not set. Refusing to start with a hardcoded fallback "
            f"secret in production. Set the {var_name} environment variable."
        )
    return dev_fallback


class Config:
    SECRET_KEY = _require_env("SMS_SECRET_KEY", _DEV_SECRET_KEY)
    JWT_SECRET = _require_env("SMS_JWT_SECRET", _DEV_JWT_SECRET)
    JWT_EXPIRY_MINUTES = 60

    DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "sms.db")
    UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
    # Raised from 5MB -> 20MB to accommodate Course Materials uploads
    # (PPT/PPTX decks can exceed 5MB). Per-module limits still apply on
    # top of this global Flask request-body cap (see course_materials.py).
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "csv", "txt"}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False

    PERMANENT_SESSION_LIFETIME = 20 * 60
    SESSION_TIMEOUT_SECONDS = 20 * 60

    MAX_FAILED_LOGINS = 5
    LOCKOUT_WINDOW_MINUTES = 10

    RATELIMIT_DEFAULT = "200 per minute"
    RATELIMIT_STORAGE_URL = "memory://"

    # ── Flask-Mail ──────────────────────────────────────────────────────
    # IMPORTANT: set these as real environment variables (never hardcode
    # real credentials in app.py / config.py). For Gmail you need an
    # "App Password" (Google Account -> Security -> 2-Step Verification ->
    # App Passwords), NOT your normal login password — Gmail rejects plain
    # passwords for SMTP.
    #
    #   Windows (PowerShell):  $env:MAIL_USERNAME="you@gmail.com"
    #                          $env:MAIL_PASSWORD="16-char-app-password"
    #                          $env:MAIL_SUPPRESS_SEND="false"
    #   Linux / Mac:           export MAIL_USERNAME="you@gmail.com"
    #                          export MAIL_PASSWORD="16-char-app-password"
    #                          export MAIL_SUPPRESS_SEND="false"
    MAIL_SERVER   = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
    MAIL_PORT     = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS  = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME or "noreply@idonportal.com")

    # BUGFIX: previously defaulted to "true" in ALL environments (including
    # production), which means Flask-Mail silently pretended every email
    # succeeded without ever opening an SMTP connection — this is exactly
    # why "email sent" flashes appeared with nothing arriving in inboxes.
    # Now: suppressed by default only in development; real sends happen in
    # production unless explicitly turned off.
    MAIL_SUPPRESS_SEND = os.environ.get(
        "MAIL_SUPPRESS_SEND", "false" if _IS_PRODUCTION else "true"
    ).lower() == "true"

    # Security headers
    FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "false").lower() == "true"