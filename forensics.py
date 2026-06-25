"""
Forensic audit trail + evidence export — v2 (IDon Portal Enhanced).
Login history now includes: entry_hash, username, role.
"""
import csv
import hashlib
import io

from database import execute, query_all
from security import looks_like_injection


def _client_ip(request):
    return request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"


def _entry_hash(user_id, username, status, ip, ts_approx):
    """SHA-256 fingerprint of a login event for tamper-evidence."""
    raw = f"{user_id}|{username}|{status}|{ip}|{ts_approx}"
    return hashlib.sha256(raw.encode()).hexdigest()


def log_activity(request, user, action, module, details=""):
    try:
        execute(
            "INSERT INTO activity_logs (user_id, username, action, module, details, ip_address, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user.get("id") if user else None,
                user.get("username") if user else "anonymous",
                action, module, details,
                _client_ip(request),
                request.headers.get("User-Agent", "")[:300],
            ),
        )
    except Exception:
        pass


def log_login(request, user_id, username, status, role=None):
    try:
        ip = _client_ip(request)
        from datetime import datetime
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        eh = _entry_hash(user_id, username, status, ip, ts)
        execute(
            "INSERT INTO login_history (user_id, username, role, entry_hash, status, ip_address, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, role, eh, status, ip,
             request.headers.get("User-Agent", "")[:300]),
        )
    except Exception:
        pass


def log_file_access(request, user, filename, action):
    try:
        execute(
            "INSERT INTO file_access_logs (user_id, username, filename, action, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.get("id") if user else None,
             user.get("username") if user else "anonymous",
             filename, action, _client_ip(request)),
        )
    except Exception:
        pass


def record_injection_alert(request, user, field, payload):
    try:
        execute(
            "INSERT INTO injection_alerts (user_id, username, input_field, payload, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.get("id") if user else None,
             user.get("username") if user else "anonymous",
             field, payload[:500], _client_ip(request)),
        )
    except Exception:
        pass


def guard_input(request, user, field, value):
    if value and looks_like_injection(value):
        record_injection_alert(request, user or {}, field, value)
        return True
    return False


_EXPORTS = {
    "activity": ("activity_logs",
                 ["id", "user_id", "username", "action", "module", "details",
                  "ip_address", "user_agent", "timestamp"]),
    "logins": ("login_history",
               ["id", "user_id", "username", "role", "entry_hash", "status",
                "ip_address", "user_agent", "timestamp"]),
    "files": ("file_access_logs",
              ["id", "user_id", "username", "filename", "action",
               "ip_address", "timestamp"]),
    "alerts": ("injection_alerts",
               ["id", "user_id", "username", "input_field", "payload",
                "ip_address", "alert_time"]),
}


def export_csv(kind):
    if kind not in _EXPORTS:
        raise ValueError("Unknown evidence type")
    table, columns = _EXPORTS[kind]
    rows = query_all(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id DESC")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r[c] for c in columns])
    return f"evidence_{kind}.csv", buf.getvalue()
