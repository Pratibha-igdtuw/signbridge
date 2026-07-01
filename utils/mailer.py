"""
Email notification helper — IDon Portal Enhanced.
All sends are wrapped in try/except so a misconfigured mail server
never crashes the application.  Set MAIL_SUPPRESS_SEND=true (default)
to disable sending entirely during development.
"""
from flask import current_app
from flask_mail import Message


def send_mail(to, subject, body_html, cc=None, bcc=None):
    """
    Send an HTML email.  Silently swallows errors so callers don't need try/except.
    Returns True on success, False on failure/suppressed.
    """
    try:
        from app import mail  # imported here to avoid circular import at module load
        msg = Message(
            subject=subject,
            recipients=[to] if isinstance(to, str) else to,
            html=body_html,
            cc=cc or [],
            bcc=bcc or [],
        )
        mail.send(msg)
        return True
    except Exception as e:
        try:
            current_app.logger.warning(f"[mailer] Failed to send '{subject}' to {to}: {e}")
        except Exception:
            pass
        return False


def notify_leave_reviewed(student_email, student_name, status, remark=""):
    status_label = "approved" if status == "approved" else "rejected"
    colour = "#16a34a" if status == "approved" else "#dc2626"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:{colour}">Leave Application {status_label.title()}</h2>
      <p>Dear {student_name},</p>
      <p>Your leave application has been <strong>{status_label}</strong>.</p>
      {"<p><em>Remark: " + remark + "</em></p>" if remark else ""}
      <p style="color:#64748b;font-size:12px">IDon Portal — Secure SMS</p>
    </div>"""
    return send_mail(student_email, f"Leave Application {status_label.title()} — IDon Portal", html)


def notify_grievance_response(student_email, student_name, response_text):
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#0d9488">Grievance Response Received</h2>
      <p>Dear {student_name},</p>
      <p>Your grievance has received a response:</p>
      <blockquote style="border-left:3px solid #0d9488;padding-left:12px;color:#374151">
        {response_text}
      </blockquote>
      <p style="color:#64748b;font-size:12px">IDon Portal — Secure SMS</p>
    </div>"""
    return send_mail(student_email, "Grievance Response — IDon Portal", html)


def notify_low_attendance(student_email, student_name, subject, pct):
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#b45309">⚠️ Low Attendance Alert</h2>
      <p>Dear {student_name},</p>
      <p>Your attendance in <strong>{subject}</strong> has dropped to
         <strong style="color:#dc2626">{pct}%</strong>, which is below the
         required 75%.</p>
      <p>Please contact your faculty immediately.</p>
      <p style="color:#64748b;font-size:12px">IDon Portal — Secure SMS</p>
    </div>"""
    return send_mail(student_email, f"Low Attendance Alert: {subject} — IDon Portal", html)


def notify_fee_update(student_email, student_name, semester, fee_type, status):
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#0d9488">Fee Status Updated</h2>
      <p>Dear {student_name},</p>
      <p>Your <strong>{fee_type}</strong> fee for Semester {semester} has been
         updated to <strong>{status}</strong>.</p>
      <p>Log in to the portal to view details.</p>
      <p style="color:#64748b;font-size:12px">IDon Portal — Secure SMS</p>
    </div>"""
    return send_mail(student_email, "Fee Status Update — IDon Portal", html)


def notify_new_notice(student_emails, title, body_preview):
    """Broadcast a notice to all students in batches of 50."""
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#0d9488">New Notice: {title}</h2>
      <p>{body_preview[:300]}{"..." if len(body_preview) > 300 else ""}</p>
      <p>Log in to the IDon Portal for full details.</p>
      <p style="color:#64748b;font-size:12px">IDon Portal — Secure SMS</p>
    </div>"""
    sent = 0
    batch_size = 50
    emails = list(student_emails)
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        ok = send_mail(
            to=batch[0],
            subject=f"New Notice: {title} — IDon Portal",
            body_html=html,
            bcc=batch[1:],
        )
        if ok:
            sent += len(batch)
    return sent


def notify_account_approved(email, full_name):
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#16a34a">Account Approved</h2>
      <p>Dear {full_name},</p>
      <p>Your IDon Portal account has been <strong>approved</strong> by the administrator.
         You can now log in.</p>
      <p style="color:#64748b;font-size:12px">IDon Portal — Secure SMS</p>
    </div>"""
    return send_mail(email, "Account Approved — IDon Portal", html)
