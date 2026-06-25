"""
Configuration for the Secure Student Management System v3.
"""
import os


class Config:
    SECRET_KEY = os.environ.get("SMS_SECRET_KEY", "change-me-in-production-7f3a9c1e")
    JWT_SECRET = os.environ.get("SMS_JWT_SECRET", "change-me-jwt-2b8d4f6a")
    JWT_EXPIRY_MINUTES = 60

    DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "sms.db")
    UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "csv", "txt"}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False

    # Session timeout: 20 minutes idle
    PERMANENT_SESSION_LIFETIME = 20 * 60
    SESSION_TIMEOUT_SECONDS = 20 * 60

    MAX_FAILED_LOGINS = 5
    LOCKOUT_WINDOW_MINUTES = 10

    RATELIMIT_DEFAULT = "200 per minute"
    RATELIMIT_STORAGE_URL = "memory://"
