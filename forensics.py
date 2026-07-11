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


# ----------------------------------------------------------------------------
# Section 63(4)(c) Bharatiya Sakshya Adhiniyam, 2023 — Certificate export
# ----------------------------------------------------------------------------
# Every kind of forensic evidence the portal can export as CSV can also be
# exported as a signed-ready electronic evidence certificate, mirroring the
# two-part "Schedule" form prescribed under section 63(4)(c) of the BSA 2023
# (successor to section 65B of the Indian Evidence Act, 1872).  Part A is
# the declaration of the "Party" producing the record (the portal / data
# custodian) and Part B is the declaration of the "Expert" who technically
# verifies it. The hash quoted on the certificate is computed over the exact
# bytes of the matching CSV export, so the certificate and the CSV are
# cryptographically tied together as one piece of evidence.

_EVIDENCE_LABELS = {
    "activity": "User Activity Logs (table: activity_logs)",
    "logins":   "Login History / Authentication Records (table: login_history)",
    "files":    "File Access Logs (table: file_access_logs)",
    "alerts":   "SQL Injection Alerts (table: injection_alerts)",
}


def _evidence_hash(kind):
    """SHA-256 over the exact CSV bytes returned by export_csv(kind)."""
    filename, csv_text = export_csv(kind)
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    row_count = max(csv_text.count("\n") - 1, 0)  # exclude header row
    return filename, csv_text, digest, row_count


def generate_certificate_pdf(kind, party=None, expert=None):
    """
    Build a Section 63(4)(c) BSA 2023 electronic-evidence certificate (PDF)
    for the given evidence `kind`. `party` is the logged-in admin producing
    the record (dict with full_name/username/role); `expert` optionally
    identifies a separate technical verifier — if omitted, the party's
    details are reused with an "Expert" designation, since the portal's
    forensic module itself performs the technical hash verification.

    Returns (filename, pdf_bytes).
    """
    if kind not in _EXPORTS:
        raise ValueError("Unknown evidence type")

    from datetime import datetime, timedelta
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    _, _, digest, row_count = _evidence_hash(kind)
    source_label = _EVIDENCE_LABELS.get(kind, kind)

    party = party or {}
    expert = expert or party

    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    date_str = ist_now.strftime("%d/%m/%Y")
    time_str = ist_now.strftime("%H:%M")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    L = 20 * mm
    R = width - 20 * mm

    def checkbox(x, y, size=3.6 * mm, checked=False):
        c.rect(x, y, size, size)
        if checked:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x + 0.8, y + 0.9, "X")

    def wrapped(text, x, y, max_width, font="Helvetica", size=9, leading=12):
        c.setFont(font, size)
        words = text.split(" ")
        line = ""
        for w in words:
            trial = (line + " " + w).strip()
            if c.stringWidth(trial, font, size) > max_width and line:
                c.drawString(x, y, line)
                y -= leading
                line = w
            else:
                line = trial
        if line:
            c.drawString(x, y, line)
            y -= leading
        return y

    def draw_part(part_letter, part_role, role_desc, person, designation_note):
        y = height - 20 * mm
        c.setFont("Helvetica", 8)
        c.drawString(L, y, "THE GAZETTE OF INDIA EXTRAORDINARY")
        y -= 10 * mm

        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(width / 2, y, "THE SCHEDULE")
        y -= 6 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(width / 2, y, "[See section 63(4)(c), Bharatiya Sakshya Adhiniyam, 2023]")
        y -= 7 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, y, "CERTIFICATE")
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y, f"PART {part_letter}")
        y -= 5 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(width / 2, y, f"(To be filled by the {part_role})")
        y -= 9 * mm

        name = person.get("full_name") or person.get("username") or "_" * 30
        c.setFont("Helvetica", 9)
        y = wrapped(
            f"I, {name} ({designation_note}), do hereby solemnly affirm and "
            f"sincerely state and submit as follows:\u2014",
            L, y, R - L)
        y -= 3 * mm

        lead = ("I have produced electronic record/output of the digital record taken "
                "from the following device/digital record source (tick mark):\u2014"
                if part_letter == "A" else
                "The produced electronic record/output of the digital record are "
                "obtained from the following device/digital record source (tick mark):\u2014")
        y = wrapped(lead, L, y, R - L)
        y -= 3 * mm

        opts = [("Computer / Storage Media", False), ("DVR", False), ("Mobile", False),
                ("Flash Drive", False), ("CD/DVD", False), ("Server", True),
                ("Cloud", False), ("Other", False)]
        x = L
        c.setFont("Helvetica", 9)
        for label, checked in opts:
            checkbox(x, y - 3, checked=checked)
            c.drawString(x + 5 * mm, y - 3, label)
            x += c.stringWidth(label, "Helvetica", 9) + 12 * mm
            if x > R - 25 * mm:
                x = L
                y -= 6 * mm
        y -= 9 * mm

        c.setFont("Helvetica", 9)
        c.drawString(L, y, "Make & Model:  Flask application server (SQLite database engine)")
        y -= 6 * mm
        c.drawString(L, y, "Digital record source:  IDon Portal — Secure Student Management System")
        y -= 6 * mm
        c.drawString(L, y, f"Evidence category:  {source_label}")
        y -= 6 * mm
        c.drawString(L, y, f"Record count at time of export:  {row_count}")
        y -= 9 * mm

        if part_letter == "A":
            y = wrapped(
                "The digital device or the digital record source was under the lawful "
                "control for regularly creating, storing or processing information for "
                "the purposes of carrying out regular activities, and during this period "
                "the computer/communication device was working properly and the relevant "
                "information was regularly fed into it during the ordinary course of "
                "business. If the device was, at any point, not working properly or out "
                "of operation, that has not affected the record or its accuracy. The "
                "digital device or source of the digital record is:\u2014",
                L, y, R - L, leading=11)
            y -= 2 * mm
            opts2 = [("Owned", False), ("Maintained", True), ("Managed", True), ("Operated", True)]
            x = L
            for label, checked in opts2:
                checkbox(x, y - 3, checked=checked)
                c.drawString(x + 5 * mm, y - 3, label)
                x += c.stringWidth(label, "Helvetica", 9) + 20 * mm
            y -= 6 * mm
            c.drawString(L, y, "by the party named above (select as applicable).")
            y -= 9 * mm

        y = wrapped(
            f"I state that the HASH value of the electronic/digital record is "
            f"{digest}, obtained through the following algorithm:\u2014",
            L, y, R - L)
        y -= 3 * mm

        for label, checked in [("SHA1", False), ("SHA256", True), ("MD5", False), ("Other", False)]:
            checkbox(L, y - 3, checked=checked)
            c.drawString(L + 5 * mm, y - 3, label + (" (this certificate)" if checked else ""))
            y -= 6 * mm
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(L, y, "(Hash report / matching CSV evidence export to be enclosed with this certificate)")
        y -= 14 * mm

        c.setFont("Helvetica", 9)
        c.line(R - 65 * mm, y, R, y)
        y -= 5 * mm
        sig_label = "(Name and signature)" if part_letter == "A" else "(Name, designation and signature)"
        c.drawRightString(R, y, sig_label)
        y -= 8 * mm
        c.drawString(L, y, f"Date (DD/MM/YYYY):  {date_str}")
        y -= 6 * mm
        c.drawString(L, y, f"Time (IST):  {time_str} hours (24-hour format)")
        y -= 6 * mm
        c.drawString(L, y, "Place:  New Delhi")
        y -= 14 * mm

        c.setFont("Helvetica-Oblique", 7.5)
        y = wrapped(
            "This certificate was auto-drafted by the IDon Portal forensic module "
            "from live audit-trail data; the declarant's wet-ink signature above is "
            "required to complete the section 63(4)(c) declaration.",
            L, y, R - L, font="Helvetica-Oblique", size=7.5, leading=9)

    draw_part("A", "Party", "the Party producing the record",
              party, "Data Custodian, IDon Portal")
    c.showPage()
    draw_part("B", "Expert", "the technical Expert",
              expert, "Technical Verifier, IDon Portal Forensic Module")
    c.showPage()
    c.save()

    return f"certificate_63_4_c_{kind}.pdf", buf.getvalue()