"""
Configuration for the Secure Student Management System v3 Enhanced.
"""
import os


class Config:
    SECRET_KEY = os.environ.get("SMS_SECRET_KEY", "change-me-in-production-7f3a9c1e")
    JWT_SECRET = os.environ.get("SMS_JWT_SECRET", "change-me-jwt-2b8d4f6a")
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

    # Flask-Mail
    MAIL_SERVER   = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
    MAIL_PORT     = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS  = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@idonportal.com")
    MAIL_SUPPRESS_SEND = os.environ.get("MAIL_SUPPRESS_SEND", "true").lower() == "true"

    # Security headers
    FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "false").lower() == "true"
