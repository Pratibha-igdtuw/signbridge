"""
Authentication & access control — v3.

  - Password hashing      -> Werkzeug PBKDF2
  - Session management     -> Flask signed-cookie + idle timeout
  - JWT Authentication     -> issued for the API layer (/api/*)
  - RBAC                   -> login_required / role_required decorators

Session idle timeout: every request refreshes a `_last_active` timestamp in
the session; if the gap since the last request exceeds SESSION_TIMEOUT_SECONDS
the session is expired and the user is redirected to login.
"""
from datetime import datetime, timedelta, timezone
from functools import wraps
from time import time

import jwt
from flask import session, redirect, url_for, flash, request, jsonify, abort

from config import Config


# ----------------------------- JWT helpers ----------------------------------
def issue_jwt(user):
    payload = {
        "sub": user["id"],
        "username": user["username"],
        "role": user["role"],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=Config.JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, Config.JWT_SECRET, algorithm="HS256")


def decode_jwt(token):
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def current_user():
    """The logged-in web user as a plain dict, or None."""
    if "user_id" in session:
        return {
            "id": session["user_id"],
            "username": session.get("username"),
            "role": session.get("role"),
            "full_name": session.get("full_name"),
        }
    return None


# ----------------------- Session idle-timeout check ------------------------
def _check_session_timeout():
    """Return True if session has expired due to inactivity."""
    last = session.get("_last_active")
    now = int(time())
    if last and (now - last) > Config.SESSION_TIMEOUT_SECONDS:
        session.clear()
        return True
    session["_last_active"] = now
    return False


# --------------------------- Web (session) guards ---------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login"))
        if _check_session_timeout():
            flash("Your session expired due to inactivity. Please sign in again.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please sign in to continue.", "error")
                return redirect(url_for("login"))
            if _check_session_timeout():
                flash("Your session expired due to inactivity. Please sign in again.", "error")
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "error")
                role = session.get("role")
                if role == "student":
                    return redirect(url_for("attendance"))
                # admin/faculty hitting wrong route
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


# --------------------------- API (JWT) guard --------------------------------
def jwt_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify({"error": "Missing bearer token"}), 401
            data = decode_jwt(auth.split(" ", 1)[1])
            if not data:
                return jsonify({"error": "Invalid or expired token"}), 401
            if roles and data.get("role") not in roles:
                return jsonify({"error": "Forbidden"}), 403
            request.jwt_user = {"id": data["sub"], "username": data["username"],
                                "role": data["role"]}
            return view(*args, **kwargs)
        return wrapped
    return decorator
