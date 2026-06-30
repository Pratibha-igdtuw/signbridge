# ============================================================
# late_fee_system.py  — place in root folder next to app.py
# Late fee fine calculation using raw SQL (your project style)
# ============================================================
# FINE RULES:
#   - Grace period : 7 days after due_date (no fine)
#   - Week 1 overdue (day 8-14)  : ₹500 flat fine
#   - Week 2 overdue (day 15-21) : ₹1000 flat fine
#   - Week 3+ overdue (day 22+)  : ₹1500 flat fine
#   - Fine is per fee record (tuition, hostel, etc. charged separately)
# ============================================================

from datetime import date, timedelta

# Fine config — change these values to match your college rules
GRACE_DAYS   = 7    # days after due_date before fine starts
FINE_WEEK_1  = 50 # ₹ fine after grace + 1 week
FINE_WEEK_2  = 150 # ₹ fine after grace + 2 weeks
FINE_WEEK_3  = 500 # ₹ fine after grace + 3 weeks


def calculate_fine(due_date_str, status):
    """
    Calculate fine amount for a fee record.
    Returns (fine_amount, days_overdue, fine_reason)
    """
    if status == "paid":
        return 0, 0, ""
    if not due_date_str:
        return 0, 0, ""

    try:
        from datetime import datetime as _dt
        due_d     = _dt.strptime(str(due_date_str), "%Y-%m-%d").date()
        today     = date.today()
        days_late = (today - due_d).days   # negative = not yet due

        if days_late <= GRACE_DAYS:
            return 0, max(0, days_late), ""

        days_overdue = days_late - GRACE_DAYS

        if days_overdue <= 7:
            return FINE_WEEK_1, days_late, f"Late >1 week (₹{FINE_WEEK_1} fine)"
        elif days_overdue <= 14:
            return FINE_WEEK_2, days_late, f"Late >2 weeks (₹{FINE_WEEK_2} fine)"
        else:
            return FINE_WEEK_3, days_late, f"Late >3 weeks (₹{FINE_WEEK_3} fine)"

    except (ValueError, TypeError):
        return 0, 0, ""


def apply_fines_to_fee_rows(fee_rows):
    """
    Adds fine_amount, days_overdue, fine_reason, total_payable
    to each fee row dict. Call this before passing fee_rows to template.
    """
    enriched = []
    for f in fee_rows:
        row = dict(f)
        fine, days, reason = calculate_fine(
            row.get("due_date"), row.get("status")
        )
        balance = float(row.get("amount", 0)) - float(row.get("paid_amount", 0))
        row["fine_amount"]    = fine
        row["days_overdue"]   = days
        row["fine_reason"]    = reason
        row["balance"]        = balance
        row["total_payable"]  = max(0, balance) + fine   # what student owes now
        row["is_overdue"]     = days > GRACE_DAYS
        enriched.append(row)
    return enriched


def get_student_fine_summary(fee_rows):
    """
    Returns total fine across all fee records for a student.
    """
    total_fine    = 0
    total_balance = 0
    overdue_count = 0
    for f in fee_rows:
        total_fine    += f.get("fine_amount", 0)
        total_balance += max(0, f.get("balance", 0))
        if f.get("is_overdue"):
            overdue_count += 1
    return {
        "total_fine"    : total_fine,
        "total_balance" : total_balance,
        "total_payable" : total_balance + total_fine,
        "overdue_count" : overdue_count,
    }


def check_and_notify_fines(admin_user_id=1):
    """
    Scan all overdue fees and post a notice to the student.
    Call this from send_fee_reminders() or a daily job.
    """
    try:
        from database import query_all, execute
    except ImportError:
        return 0

    today    = date.today()
    fee_rows = query_all(
        "SELECT f.*, s.full_name student_name "
        "FROM fee_status f "
        "JOIN students s ON s.id = f.student_id "
        "WHERE f.due_date IS NOT NULL "
        "  AND f.status IN ('pending','partial')"
    )

    count = 0
    for fee in fee_rows:
        fine, days_late, reason = calculate_fine(fee["due_date"], fee["status"])
        if fine <= 0:
            continue

        balance = float(fee["amount"]) - float(fee["paid_amount"])
        if balance <= 0:
            continue

        # Avoid duplicate notices on same day
        already = query_all(
            "SELECT id FROM notices "
            "WHERE title LIKE ? AND category='fine' "
            "AND date(created_at) = date('now')",
            (f"%Sem {fee['semester']}%{fee['fee_type']}%",)
        )
        if already:
            continue

        title = (
            f"🚫 Late Fee Fine — {fee['fee_type'].title()} "
            f"Sem {fee['semester']} (+₹{fine:,})"
        )
        body = (
            f"Dear {fee['student_name']}, your {fee['fee_type'].title()} "
            f"fee of ₹{balance:,.0f} for Semester {fee['semester']} "
            f"was due on {fee['due_date']} and is now {days_late} days overdue. "
            f"A late fine of ₹{fine:,} has been applied. "
            f"Total payable now: ₹{balance + fine:,.0f}. "
            f"Please pay immediately to avoid further penalties."
        )
        execute(
            "INSERT INTO notices "
            "(title, body, category, target_role, posted_by, is_pinned) "
            "VALUES (?, ?, 'fine', 'student', ?, 0)",
            (title, body, admin_user_id)
        )
        count += 1

    return count