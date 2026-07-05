# ============================================================
# fee_due_notification.py
# Place in root folder next to app.py
# Uses raw SQLite queries — matches your project's database.py
# ============================================================

from datetime import date, timedelta


def check_fee_due_dates(db, Fee=None, Student=None, User=None, Notification=None):
    """
    Check fee records due within 2 days and insert notices.
    Uses raw SQL via your existing query_all / execute functions.
    db parameter is your database module (import database as db).
    """
    try:
        from database import query_all, query_one, execute
    except ImportError:
        return 0

    today     = date.today()
    warn_date = today + timedelta(days=2)
    count     = 0

    # Get all pending/partial fees due within 2 days
    due_fees = query_all(
        "SELECT f.*, s.full_name student_name, s.email student_email, s.user_id student_user_id "
        "FROM fee_status f "
        "JOIN students s ON s.id = f.student_id "
        "WHERE f.due_date IS NOT NULL "
        "  AND f.status IN ('pending', 'partial')"
    )

    for fee in due_fees:
        try:
            from datetime import datetime as _dt
            due_d = _dt.strptime(str(fee["due_date"]), "%Y-%m-%d").date()
            days_left = (due_d - today).days
            balance   = fee["amount"] - fee["paid_amount"]

            if not (0 <= days_left <= 2 and balance > 0):
                continue

            # Resolve which user account this student actually is, so the
            # reminder reaches only them — not every student. Try the direct
            # user_id link first, then fall back to matching by email.
            target_user_id = fee["student_user_id"]
            if not target_user_id and fee["student_email"]:
                match = query_one("SELECT id FROM users WHERE email = ?", (fee["student_email"],))
                target_user_id = match["id"] if match else None

            if not target_user_id:
                # Can't identify a specific account for this student — skip
                # rather than fall back to broadcasting to every student.
                continue

            # Check if we already sent a notice today for this exact student+fee
            already = query_all(
                "SELECT id FROM notices "
                "WHERE title LIKE ? AND category = 'fee' AND target_user_id = ? "
                "AND date(created_at) = date('now')",
                (f"%Sem {fee['semester']}%{fee['fee_type']}%", target_user_id)
            )
            if already:
                continue

            if days_left == 0:
                urgency = "TODAY"
                emoji   = "🚨"
            elif days_left == 1:
                urgency = "TOMORROW"
                emoji   = "⚠️"
            else:
                urgency = f"in {days_left} days"
                emoji   = "📅"

            title = (
                f"{emoji} Fee Due {urgency} — "
                f"{fee['fee_type'].title()} Sem {fee['semester']}"
            )
            body = (
                f"Dear {fee['student_name']}, your "
                f"{fee['fee_type'].title()} fee of ₹{balance:,.0f} "
                f"for Semester {fee['semester']} is due on "
                f"{fee['due_date']}. Please pay immediately to avoid penalties."
            )

            execute(
                "INSERT INTO notices "
                "(title, body, category, target_role, target_user_id, posted_by, is_pinned) "
                "VALUES (?, ?, 'fee', 'student', ?, 1, 0)",
                (title, body, target_user_id)
            )
            count += 1

        except (ValueError, TypeError, KeyError):
            continue

    return count