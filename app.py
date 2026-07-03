"""
IDon Portal — Secure Student Management System v2
==================================================
New features over base:
  1. Rate limiting (Flask-Limiter)
  2. Account lockout after N fails
  3. Password strength meter
  4. Real-time injection alert badge
  5. Audit log search & date filter
  6. Dashboard Chart.js bar chart
  7. File delete (admin only)
  8. Password eye toggle on login & register
  9. Profile setup on first login (name, email, contact, branch, university, year)
 10. Change password (profile settings page)
 11. Attendance tracking with <75% alert banner
 12. SGPA Calculator (client-side)
 13. Assignments upload by faculty; homework upload by student
 14. Login history includes entry_hash, username, role
 15. Dashboard hidden from student sidebar (students land on attendance)
"""
import os
import uuid

from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, jsonify, Response, abort)
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config
import database as db
from database import query_all, query_one, execute
import security as sec
import forensics as fz
from auth import (login_required, role_required, jwt_required, current_user,
                  issue_jwt)

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
os.makedirs(Config.UPLOAD_DIR, exist_ok=True)
db.init_db()
db.migrate_db()
db.seed()
db.seed_extras()
db.seed_courses()
db.backfill_user_id()
db.seed_timetable()


@app.context_processor
def inject_user():
    u = current_user()
    pending_count = 0
    if u and u["role"] == "admin":
        try:
            row = db.query_one("SELECT COUNT(*) AS c FROM users WHERE status = 'pending'")
            pending_count = row["c"] if row else 0
        except Exception:
            pending_count = 0
    return {
        "user": u,
        "config": Config,
        "pending_count": pending_count,
        # Lets templates check `{% if has_endpoint('twofa_setup') %}` before
        # calling url_for() on a route that may not be registered yet, so a
        # missing/renamed route doesn't crash every page that extends base.html.
        "has_endpoint": lambda name: name in app.view_functions,
    }


# ============================================================================
# Auth
# ============================================================================
@app.route("/")
def index():
    u = current_user()
    if not u:
        return redirect(url_for("login"))
    if u["role"] == "student":
        return redirect(url_for("attendance"))
    return redirect(url_for("dashboard"))


ALLOWED_EMAIL_DOMAIN = "igdtuw.ac.in"

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        form_data = request.form.copy()
        if form_data.get("role") not in (None, "", "student"):
            flash("Only student accounts can be created via self-registration.", "error")
            return render_template("register.html", form=request.form)

        # ── Domain check ──────────────────────────────────────────────────
        email = (request.form.get("email") or "").strip().lower()
        if not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
            flash(f"Only @{ALLOWED_EMAIL_DOMAIN} email addresses are allowed to self-register.", "error")
            return render_template("register.html", form=request.form)

        cleaned, errors = sec.validate_registration(request.form)
        for field in ("username", "email", "full_name"):
            if fz.guard_input(request, None, field, request.form.get(field, "")):
                errors.append("Input rejected: it matched a malicious pattern.")
                break
        if query_one("SELECT id FROM users WHERE username = ?", (cleaned["username"],)):
            errors.append("That username is taken.")
        if query_one("SELECT id FROM users WHERE email = ?", (cleaned["email"],)):
            errors.append("That email is already registered.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html", form=request.form)

        uid = execute(
            "INSERT INTO users (username, email, password_hash, role, full_name, profile_complete) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (cleaned["username"], cleaned["email"],
             generate_password_hash(cleaned["password"]),
             cleaned["role"], cleaned["full_name"]),
        )

        # ── Auto-link or create student record ────────────────────────────
        existing_student = query_one(
            "SELECT id FROM students WHERE email = ?", (cleaned["email"],)
        )
        if not existing_student:
            # Create placeholder — admin can fill in roll no / dept / year later
            execute(
                "INSERT OR IGNORE INTO students "
                "(roll_number, full_name, email, department, year, cgpa, phone, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cleaned["username"].upper(), cleaned["full_name"],
                 cleaned["email"], "TBD", 1, 0.0, "", uid)
            )

        fz.log_activity(request, {"id": uid, "username": cleaned["username"]},
                        "register", "auth", f"role={cleaned['role']}")
        flash("Account created successfully. Please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form={})


def _count_recent_failures(username):
    row = query_one(
        "SELECT COUNT(*) c FROM login_history "
        "WHERE username = ? AND status = 'failed' "
        "AND timestamp >= datetime('now', ?)",
        (username, f"-{Config.LOCKOUT_WINDOW_MINUTES} minutes"),
    )
    return row["c"] if row else 0


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if fz.guard_input(request, None, "login.username", username):
            fz.log_login(request, None, username, "failed")
            flash("Invalid credentials.", "error")
            return render_template("login.html")

        user = query_one("SELECT * FROM users WHERE username = ?", (username,))

        if user and not user["is_active"]:
            fz.log_login(request, user["id"], username, "locked", user["role"])
            flash("Account is locked. Contact an administrator.", "error")
            return render_template("login.html")

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]
            fz.log_login(request, user["id"], username, "success", user["role"])
            fz.log_activity(request, dict(user), "login", "auth")
            flash(f"Welcome back, {user['full_name']}.", "success")
            # Redirect to profile setup if not complete
            if not user["profile_complete"]:
                return redirect(url_for("profile_setup"))
            if user["role"] == "student":
                return redirect(url_for("attendance"))
            return redirect(url_for("dashboard"))

        uid = user["id"] if user else None
        fz.log_login(request, uid, username, "failed", user["role"] if user else None)

        if user:
            recent_failures = _count_recent_failures(username)
            if recent_failures >= Config.MAX_FAILED_LOGINS:
                execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
                fz.log_activity(request, dict(user), "account_locked", "auth",
                                f"auto-locked after {recent_failures} failed attempts")
                flash("Too many failed attempts. Account locked. Contact an administrator.", "error")
                return render_template("login.html")

        flash("Invalid credentials.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    fz.log_activity(request, current_user(), "logout", "auth")
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for("login"))


# ============================================================================
# Profile setup (first login) & change password
# ============================================================================
@app.route("/profile/setup", methods=["GET", "POST"])
@login_required
def profile_setup():
    user = current_user()
    if request.method == "POST":
        full_name   = (request.form.get("full_name") or "").strip()
        email       = (request.form.get("email") or "").strip()
        contact_no  = (request.form.get("contact_no") or "").strip()
        branch      = (request.form.get("branch") or "").strip()
        university  = (request.form.get("university") or "").strip()
        year        = request.form.get("year") or None
        errors = []
        if not full_name: errors.append("Full name is required.")
        if not email:     errors.append("Email is required.")
        if errors:
            for e in errors: flash(e, "error")
            return render_template("profile_setup.html", user=user, form=request.form)
        execute(
            "UPDATE users SET full_name=?, email=?, contact_no=?, branch=?, "
            "university=?, year=?, profile_complete=1 WHERE id=?",
            (full_name, email, contact_no, branch, university,
             int(year) if year else None, user["id"]),
        )
        session["full_name"] = full_name
        fz.log_activity(request, current_user(), "profile_setup", "auth")
        flash("Profile saved successfully!", "success")
        if user["role"] == "student":
            return redirect(url_for("attendance"))
        return redirect(url_for("dashboard"))
    return render_template("profile_setup.html", user=user, form={})


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_info":
            full_name  = (request.form.get("full_name") or "").strip()
            contact_no = (request.form.get("contact_no") or "").strip()
            branch     = (request.form.get("branch") or "").strip()
            university = (request.form.get("university") or "").strip()
            year       = request.form.get("year") or None
            execute(
                "UPDATE users SET full_name=?, contact_no=?, branch=?, university=?, year=? WHERE id=?",
                (full_name, contact_no, branch, university,
                 int(year) if year else None, u["id"]),
            )
            session["full_name"] = full_name
            fz.log_activity(request, current_user(), "profile_update", "auth")
            flash("Profile updated.", "success")
        elif action == "change_password":
            current_pw = request.form.get("current_password") or ""
            new_pw     = request.form.get("new_password") or ""
            confirm_pw = request.form.get("confirm_password") or ""
            if not check_password_hash(user_db["password_hash"], current_pw):
                flash("Current password is incorrect.", "error")
            elif len(new_pw) < 8:
                flash("New password must be at least 8 characters.", "error")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "error")
            else:
                execute("UPDATE users SET password_hash=? WHERE id=?",
                        (generate_password_hash(new_pw), u["id"]))
                fz.log_activity(request, current_user(), "password_changed", "auth")
                flash("Password changed successfully.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user_db=user_db)


# ============================================================================
# Admin: unlock user
# ============================================================================
@app.route("/users/<int:uid>/unlock", methods=["POST"])
@role_required("admin")
def user_unlock(uid):
    user = query_one("SELECT username FROM users WHERE id = ?", (uid,))
    if not user:
        abort(404)
    execute("UPDATE users SET is_active = 1 WHERE id = ?", (uid,))
    fz.log_activity(request, current_user(), "account_unlocked", "auth",
                    f"unlocked user id={uid}")
    flash(f"Account '{user['username']}' has been unlocked.", "success")
    return redirect(url_for("users_list"))


@app.route("/users")
@role_required("admin")
def users_list():
    users = query_all("SELECT id, username, full_name, role, email, is_active, created_at FROM users ORDER BY id")
    return render_template("users.html", all_users=users)


# ============================================================================
# Dashboard (admin + faculty only)
# ============================================================================
@app.route("/dashboard")
@role_required("admin", "faculty")
def dashboard():
    u = current_user()
    base_stats = {
        "students": query_one("SELECT COUNT(*) c FROM students")["c"],
        "logins_today": query_one(
            "SELECT COUNT(*) c FROM login_history WHERE date(timestamp)=date('now')"
        )["c"],
    }
    if u["role"] == "admin":
        base_stats["users"]  = query_one("SELECT COUNT(*) c FROM users")["c"]
        base_stats["alerts"] = query_one("SELECT COUNT(*) c FROM injection_alerts")["c"]
        locked_count = query_one("SELECT COUNT(*) c FROM users WHERE is_active = 0")["c"]
        failed = query_all(
            "SELECT username, ip_address, timestamp FROM login_history "
            "WHERE status='failed' ORDER BY id DESC LIMIT 5"
        )
        recent = query_all(
            "SELECT username, action, module, timestamp FROM activity_logs "
            "ORDER BY id DESC LIMIT 8"
        )
    else:
        # Faculty: no security internals
        base_stats["assignments"] = query_one(
            "SELECT COUNT(*) c FROM assignments WHERE uploaded_by = ?", (u["id"],)
        )["c"]
        base_stats["subjects"] = query_one(
            "SELECT COUNT(DISTINCT subject) c FROM attendance"
        )["c"]
        locked_count = 0
        failed = []
        recent = query_all(
            "SELECT username, action, module, timestamp FROM activity_logs "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 8",
            (u["id"],)
        )

    by_dept = query_all(
        "SELECT department, COUNT(*) c FROM students GROUP BY department ORDER BY c DESC"
    )
    low_att = query_all("""
        SELECT s.full_name, s.roll_number, att.subject,
               ROUND(100.0 * SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
        FROM attendance att
        JOIN students s ON s.id = att.student_id
        GROUP BY att.student_id, att.subject
        HAVING pct < 75
        ORDER BY pct ASC
        LIMIT 10
    """)
    open_grievances = query_one(
        "SELECT COUNT(*) c FROM grievances WHERE status IN ('open','in_review')"
    )["c"]
    pinned_notices = query_all(
        "SELECT title, category, created_at FROM notices "
        "WHERE is_pinned=1 AND (target_role='all' OR target_role=?) "
        "ORDER BY id DESC LIMIT 3",
        (u["role"],)
    )
    upcoming_exams = query_all(
        "SELECT subject, exam_type, exam_date, exam_time, venue FROM exam_schedule "
        "WHERE exam_date >= date('now') ORDER BY exam_date ASC LIMIT 5"
    )
    return render_template("dashboard.html", stats=base_stats, by_dept=by_dept,
                           recent=recent, failed=failed, locked_count=locked_count,
                           low_att=low_att, open_grievances=open_grievances,
                           pinned_notices=pinned_notices, upcoming_exams=upcoming_exams)


@app.route("/api/alert-count")
@login_required
def api_alert_count():
    count = query_one("SELECT COUNT(*) c FROM injection_alerts")["c"]
    return jsonify({"count": count})


# ============================================================================
# Attendance
# ============================================================================
@app.route("/attendance")
@login_required
def attendance():
    u = current_user()
    selected_student = None
    att_data = []
    low_subjects = []
    my_courses = []
    course_filter = None

    if u["role"] == "student":
        user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
        selected_student = query_one("SELECT * FROM students WHERE user_id = ?", (u["id"],))
        if not selected_student:
            selected_student = query_one("SELECT * FROM students WHERE email = ?", (user_db["email"],))
        if not selected_student:
            selected_student = query_one("SELECT * FROM students WHERE full_name = ?", (user_db["full_name"],))
        sid = selected_student["id"] if selected_student else None
        students = []
    elif u["role"] == "faculty":
        # Faculty: scoped to their courses
        my_courses = query_all(
            "SELECT c.id, c.name, c.code, c.subject, c.semester, c.department, c.section "
            "FROM courses c JOIN course_faculty cf ON cf.course_id=c.id "
            "WHERE cf.faculty_id=? ORDER BY c.department, c.semester, c.name",
            (u["id"],)
        )
        course_filter = request.args.get("course_id") or None
        if course_filter:
            course_filter = int(course_filter)
            students = query_all(
                "SELECT s.* FROM students s JOIN enrollments e ON e.student_id=s.id "
                "WHERE e.course_id=? ORDER BY s.roll_number",
                (course_filter,)
            )
        else:
            students = query_all(
                "SELECT DISTINCT s.* FROM students s "
                "JOIN enrollments e ON e.student_id=s.id "
                "JOIN course_faculty cf ON cf.course_id=e.course_id "
                "WHERE cf.faculty_id=? ORDER BY s.roll_number",
                (u["id"],)
            )
        sid = request.args.get("student_id") or None
    else:
        # Admin sees all
        students = query_all("SELECT * FROM students ORDER BY roll_number")
        sid = request.args.get("student_id") or None

    if sid:
        selected_student = query_one("SELECT * FROM students WHERE id = ?", (sid,))
        att_data = query_all("""
            SELECT subject,
                   COUNT(*) total,
                   SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) present,
                   ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
            FROM attendance WHERE student_id = ?
            GROUP BY subject ORDER BY subject
        """, (sid,))
        low_subjects = [r for r in att_data if r["pct"] < 75]

    return render_template("attendance.html", students=students,
                           selected_student=selected_student,
                           att_data=att_data, low_subjects=low_subjects,
                           sid=int(sid) if sid else None,
                           my_courses=my_courses, course_filter=course_filter)


@app.route("/attendance/mark", methods=["POST"])
@role_required("admin", "faculty")
def attendance_mark():
    student_id = request.form.get("student_id")
    subject    = (request.form.get("subject") or "").strip()
    date_val   = (request.form.get("date") or "").strip()
    status     = request.form.get("status")
    if not all([student_id, subject, date_val, status]):
        flash("All fields are required.", "error")
        return redirect(url_for("attendance"))
    try:
        execute(
            "INSERT OR REPLACE INTO attendance (student_id, subject, date, status, marked_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(student_id), subject, date_val, status, session["user_id"])
        )
        flash("Attendance marked.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("attendance", student_id=student_id))


# ============================================================================
# SGPA Calculator (page only — computation is client-side)
# ============================================================================
# Assignments (faculty upload) & Homework (student upload)
# ============================================================================
def _allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


ALLOWED_MIME_TYPES = {
    "application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp",
    "text/plain", "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    "application/x-zip-compressed",
}


def _allowed_file_safe(file_storage):
    """Check both extension AND actual MIME type via python-magic."""
    name = file_storage.filename or ""
    if not _allowed_file(name):
        return False, "File extension not allowed."
    # Check actual MIME type
    try:
        import magic
        header = file_storage.stream.read(2048)
        file_storage.stream.seek(0)
        mime = magic.from_buffer(header, mime=True)
        if mime not in ALLOWED_MIME_TYPES:
            return False, f"File content type '{mime}' is not permitted."
    except ImportError:
        pass  # python-magic not available, fall back to extension check
    return True, None


@app.route("/assignments")
@login_required
def assignments():
    u = current_user()
    if u["role"] in ("admin", "faculty"):
        rows = query_all(
            "SELECT a.*, u.full_name uploader_name FROM assignments a "
            "LEFT JOIN users u ON a.uploaded_by = u.id ORDER BY a.id DESC"
        )
    else:
        # Students see assignments for their dept/year
        user_db = query_one("SELECT branch, year FROM users WHERE id = ?", (u["id"],))
        rows = query_all(
            "SELECT a.*, u.full_name uploader_name FROM assignments a "
            "LEFT JOIN users u ON a.uploaded_by = u.id "
            "WHERE (a.department IS NULL OR a.department = ? OR a.department = '') "
            "  AND (a.year IS NULL OR a.year = 0 OR a.year = ?) "
            "ORDER BY a.id DESC",
            (user_db["branch"] or "", user_db["year"] or 0)
        )

    # For each assignment, check if student has submitted
    submissions = {}
    if u["role"] == "student":
        user_db = query_one("SELECT email, full_name FROM users WHERE id = ?", (u["id"],))
        student = query_one("SELECT id FROM students WHERE email = ? OR full_name = ?",
                            (user_db["email"], user_db["full_name"]))
        if student:
            subs = query_all("SELECT assignment_id FROM homework_submissions WHERE student_id = ?",
                             (student["id"],))
            submissions = {s["assignment_id"] for s in subs}

    return render_template("assignments.html", assignments=rows, submissions=submissions)


@app.route("/assignments/upload", methods=["POST"])
@role_required("admin", "faculty")
def assignment_upload():
    title       = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    subject     = (request.form.get("subject") or "").strip()
    department  = (request.form.get("department") or "").strip()
    year        = request.form.get("year") or None
    due_date    = (request.form.get("due_date") or "").strip()
    f = request.files.get("file")
    errors = []
    if not title: errors.append("Title is required.")
    if not subject: errors.append("Subject is required.")
    if not f or f.filename == "":
        errors.append("Please attach a file.")
    else:
        ok, mime_err = _allowed_file_safe(f)
        if not ok:
            errors.append(mime_err or "File type not allowed.")
    if errors:
        for e in errors: flash(e, "error")
        return redirect(url_for("assignments"))
    safe_name = secure_filename(f.filename)
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    f.save(os.path.join(Config.UPLOAD_DIR, stored_name))
    execute(
        "INSERT INTO assignments (title, description, subject, department, year, "
        "due_date, stored_name, original_name, uploaded_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (title, description, subject, department,
         int(year) if year else None, due_date, stored_name, safe_name, session["user_id"])
    )
    fz.log_activity(request, current_user(), "assignment_upload", "assignments", f"title={title}")
    flash("Assignment uploaded.", "success")
    return redirect(url_for("assignments"))


@app.route("/assignments/<int:aid>/download")
@login_required
def assignment_download(aid):
    row = query_one("SELECT * FROM assignments WHERE id = ?", (aid,))
    if not row: abort(404)
    path = os.path.join(Config.UPLOAD_DIR, row["stored_name"])
    if not os.path.exists(path): abort(404)
    fz.log_activity(request, current_user(), "assignment_download", "assignments", f"id={aid}")
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(data, headers={
        "Content-Disposition": f'attachment; filename="{row["original_name"]}"',
        "Content-Type": "application/octet-stream",
    })


@app.route("/assignments/<int:aid>/delete", methods=["POST"])
@role_required("admin", "faculty")
def assignment_delete(aid):
    row = query_one("SELECT * FROM assignments WHERE id = ?", (aid,))
    if not row: abort(404)
    path = os.path.join(Config.UPLOAD_DIR, row["stored_name"])
    if os.path.exists(path): os.remove(path)
    execute("DELETE FROM assignments WHERE id = ?", (aid,))
    flash("Assignment deleted.", "success")
    return redirect(url_for("assignments"))


@app.route("/assignments/<int:aid>/submit", methods=["POST"])
@role_required("student")
def homework_submit(aid):
    u = current_user()
    user_db = query_one("SELECT email, full_name FROM users WHERE id = ?", (u["id"],))
    student = query_one("SELECT id FROM students WHERE email = ? OR full_name = ?",
                        (user_db["email"], user_db["full_name"]))
    if not student:
        flash("Your student record was not found. Contact admin.", "error")
        return redirect(url_for("assignments"))
    # Fetch assignment and check due date
    assignment = query_one("SELECT * FROM assignments WHERE id = ?", (aid,))
    if not assignment:
        abort(404)
    is_late = 0
    if assignment["due_date"]:
        from datetime import datetime as _dt
        try:
            due = _dt.strptime(assignment["due_date"], "%Y-%m-%d")
            if _dt.utcnow() > due.replace(hour=23, minute=59, second=59):
                is_late = 1
                flash("⚠️ Note: This submission is past the due date and will be marked late.", "warning")
        except ValueError:
            pass
    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Please attach your homework file.", "error")
        return redirect(url_for("assignments"))
    ok, mime_err = _allowed_file_safe(f)
    if not ok:
        flash(mime_err or "File type not allowed.", "error")
        return redirect(url_for("assignments"))
    safe_name = secure_filename(f.filename)
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    f.save(os.path.join(Config.UPLOAD_DIR, stored_name))
    try:
        execute(
            "INSERT OR REPLACE INTO homework_submissions (assignment_id, student_id, stored_name, original_name, is_late) "
            "VALUES (?, ?, ?, ?, ?)",
            (aid, student["id"], stored_name, safe_name, is_late)
        )
        fz.log_activity(request, current_user(), "homework_submit", "assignments", f"aid={aid}")
        flash("Homework submitted successfully!", "success")
    except Exception as e:
        flash(f"Submission error: {e}", "error")
    return redirect(url_for("assignments"))


@app.route("/assignments/<int:aid>/submissions")
@role_required("admin", "faculty")
def homework_list(aid):
    assignment = query_one("SELECT * FROM assignments WHERE id = ?", (aid,))
    if not assignment: abort(404)
    subs = query_all("""
        SELECT hs.*, s.full_name student_name, s.roll_number
        FROM homework_submissions hs
        JOIN students s ON s.id = hs.student_id
        WHERE hs.assignment_id = ?
        ORDER BY hs.submitted_at DESC
    """, (aid,))
    return render_template("homework_list.html", assignment=assignment, subs=subs)


@app.route("/homework/<int:hid>/download")
@role_required("admin", "faculty")
def homework_download(hid):
    row = query_one("SELECT * FROM homework_submissions WHERE id = ?", (hid,))
    if not row: abort(404)
    path = os.path.join(Config.UPLOAD_DIR, row["stored_name"])
    if not os.path.exists(path): abort(404)
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(data, headers={
        "Content-Disposition": f'attachment; filename="{row["original_name"]}"',
        "Content-Type": "application/octet-stream",
    })


# ============================================================================
# Student records
# ============================================================================
@app.route("/students")
@login_required
def students():
    u = current_user()
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "created_at")
    direction = request.args.get("dir", "DESC")
    if fz.guard_input(request, current_user(), "students.search", q):
        flash("Search input rejected.", "error")
        q = ""
    col, dir_ = sec.safe_sort(sort, direction)

    if u["role"] == "admin":
        # Admin sees all students
        if q:
            rows = query_all(
                f"SELECT * FROM students WHERE roll_number LIKE ? OR full_name LIKE ? OR email LIKE ? ORDER BY {col} {dir_}",
                (f"%{q}%", f"%{q}%", f"%{q}%"),
            )
        else:
            rows = query_all(f"SELECT * FROM students ORDER BY {col} {dir_}")
        my_courses = []
    elif u["role"] == "faculty":
        # Faculty sees only students enrolled in their courses
        my_courses = query_all(
            "SELECT c.id, c.name, c.code, c.subject, c.semester, c.department, c.section, c.academic_year "
            "FROM courses c JOIN course_faculty cf ON cf.course_id=c.id "
            "WHERE cf.faculty_id=? ORDER BY c.department, c.semester, c.name",
            (u["id"],)
        )
        course_filter = request.args.get("course_id") or None
        if course_filter:
            # Verify this course belongs to this faculty
            valid = query_one(
                "SELECT id FROM course_faculty WHERE course_id=? AND faculty_id=?",
                (int(course_filter), u["id"])
            )
            if not valid:
                flash("You are not assigned to that course.", "error")
                return redirect(url_for("students"))
            if q:
                rows = query_all(
                    f"SELECT s.* FROM students s "
                    f"JOIN enrollments e ON e.student_id=s.id "
                    f"WHERE e.course_id=? AND (s.roll_number LIKE ? OR s.full_name LIKE ?) "
                    f"ORDER BY s.{col} {dir_}",
                    (int(course_filter), f"%{q}%", f"%{q}%")
                )
            else:
                rows = query_all(
                    f"SELECT s.* FROM students s "
                    f"JOIN enrollments e ON e.student_id=s.id "
                    f"WHERE e.course_id=? ORDER BY s.{col} {dir_}",
                    (int(course_filter),)
                )
        else:
            # No course selected — show students across all faculty courses
            if q:
                rows = query_all(
                    f"SELECT DISTINCT s.* FROM students s "
                    f"JOIN enrollments e ON e.student_id=s.id "
                    f"JOIN course_faculty cf ON cf.course_id=e.course_id "
                    f"WHERE cf.faculty_id=? AND (s.roll_number LIKE ? OR s.full_name LIKE ?) "
                    f"ORDER BY s.{col} {dir_}",
                    (u["id"], f"%{q}%", f"%{q}%")
                )
            else:
                rows = query_all(
                    f"SELECT DISTINCT s.* FROM students s "
                    f"JOIN enrollments e ON e.student_id=s.id "
                    f"JOIN course_faculty cf ON cf.course_id=e.course_id "
                    f"WHERE cf.faculty_id=? ORDER BY s.{col} {dir_}",
                    (u["id"],)
                )
        course_filter = int(course_filter) if course_filter else None
        fz.log_activity(request, current_user(), "view_list", "students", f"q='{q}'")
        return render_template("students.html", students=rows, q=q, sort=col, dir=dir_,
                               my_courses=my_courses, course_filter=course_filter)
    else:
        rows = []
        my_courses = []

    fz.log_activity(request, current_user(), "view_list", "students", f"q='{q}'")
    return render_template("students.html", students=rows, q=q, sort=col, dir=dir_,
                           my_courses=[], course_filter=None)


@app.route("/students/new", methods=["GET", "POST"])
@role_required("admin", "faculty")
def student_new():
    if request.method == "POST":
        cleaned, errors = sec.validate_student(request.form)
        for field in ("roll_number", "full_name", "email"):
            if fz.guard_input(request, current_user(), f"student.{field}",
                              request.form.get(field, "")):
                errors.append("Input rejected.")
                break
        if query_one("SELECT id FROM students WHERE roll_number = ?", (cleaned["roll_number"],)):
            errors.append("A student with that roll number already exists.")
        if errors:
            for e in errors: flash(e, "error")
            return render_template("student_form.html", form=request.form, mode="new")
        sid = execute(
            "INSERT INTO students (roll_number, full_name, email, department, year, cgpa, phone, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cleaned["roll_number"], cleaned["full_name"], cleaned["email"],
             cleaned["department"], cleaned["year"], cleaned["cgpa"],
             cleaned["phone"], session["user_id"]),
        )
        fz.log_activity(request, current_user(), "create", "students", f"roll={cleaned['roll_number']}")
        flash("Student added.", "success")
        return redirect(url_for("students"))
    return render_template("student_form.html", form={}, mode="new")


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
@role_required("admin", "faculty")
def student_edit(sid):
    student = query_one("SELECT * FROM students WHERE id = ?", (sid,))
    if not student: abort(404)
    if request.method == "POST":
        cleaned, errors = sec.validate_student(request.form)
        clash = query_one("SELECT id FROM students WHERE roll_number = ? AND id != ?",
                          (cleaned["roll_number"], sid))
        if clash: errors.append("Another student already has that roll number.")
        if errors:
            for e in errors: flash(e, "error")
            return render_template("student_form.html", form=request.form, mode="edit", sid=sid)
        execute(
            "UPDATE students SET roll_number=?, full_name=?, email=?, department=?, "
            "year=?, cgpa=?, phone=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (cleaned["roll_number"], cleaned["full_name"], cleaned["email"],
             cleaned["department"], cleaned["year"], cleaned["cgpa"], cleaned["phone"], sid),
        )
        fz.log_activity(request, current_user(), "update", "students", f"id={sid}")
        flash("Student updated.", "success")
        return redirect(url_for("students"))
    return render_template("student_form.html", form=dict(student), mode="edit", sid=sid)


@app.route("/students/<int:sid>/delete", methods=["POST"])
@role_required("admin")
def student_delete(sid):
    student = query_one("SELECT roll_number FROM students WHERE id = ?", (sid,))
    if not student: abort(404)
    execute("DELETE FROM students WHERE id = ?", (sid,))
    fz.log_activity(request, current_user(), "delete", "students", f"id={sid}")
    flash("Student deleted.", "success")
    return redirect(url_for("students"))


# ============================================================================
# File upload (general)
# ============================================================================
@app.route("/files", methods=["GET"])
@role_required("admin", "faculty")
def files():
    rows = query_all(
        "SELECT f.*, u.username uploader, s.roll_number roll "
        "FROM uploaded_files f LEFT JOIN users u ON f.uploaded_by = u.id "
        "LEFT JOIN students s ON f.student_id = s.id ORDER BY f.id DESC"
    )
    student_opts = query_all("SELECT id, roll_number, full_name FROM students ORDER BY roll_number")
    return render_template("files.html", files=rows, students=student_opts)


@app.route("/files/upload", methods=["POST"])
@role_required("admin", "faculty")
def file_upload():
    f = request.files.get("file")
    student_id = request.form.get("student_id") or None
    if not f or f.filename == "":
        flash("Choose a file first.", "error")
        return redirect(url_for("files"))
    ok, mime_err = _allowed_file_safe(f)
    if not ok:
        flash(mime_err or "File type not allowed.", "error")
        return redirect(url_for("files"))
    safe_name = secure_filename(f.filename)
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    path = os.path.join(Config.UPLOAD_DIR, stored_name)
    f.save(path)
    size = os.path.getsize(path)
    fid = execute(
        "INSERT INTO uploaded_files (original_name, stored_name, uploaded_by, student_id, file_size) "
        "VALUES (?, ?, ?, ?, ?)",
        (safe_name, stored_name, session["user_id"],
         int(student_id) if student_id else None, size),
    )
    fz.log_file_access(request, current_user(), safe_name, "upload")
    flash("File uploaded.", "success")
    return redirect(url_for("files"))


@app.route("/files/<int:fid>/download")
@role_required("admin", "faculty")
def file_download(fid):
    row = query_one("SELECT * FROM uploaded_files WHERE id = ?", (fid,))
    if not row: abort(404)
    path = os.path.join(Config.UPLOAD_DIR, row["stored_name"])
    if not os.path.exists(path): abort(404)
    fz.log_file_access(request, current_user(), row["original_name"], "download")
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(data, headers={
        "Content-Disposition": f'attachment; filename="{row["original_name"]}"',
        "Content-Type": "application/octet-stream",
    })


@app.route("/files/<int:fid>/delete", methods=["POST"])
@role_required("admin")
def file_delete(fid):
    row = query_one("SELECT * FROM uploaded_files WHERE id = ?", (fid,))
    if not row: abort(404)
    path = os.path.join(Config.UPLOAD_DIR, row["stored_name"])
    if os.path.exists(path): os.remove(path)
    execute("DELETE FROM uploaded_files WHERE id = ?", (fid,))
    fz.log_file_access(request, current_user(), row["original_name"], "delete")
    flash(f"File '{row['original_name']}' deleted.", "success")
    return redirect(url_for("files"))


# ============================================================================
# Forensic audit
# ============================================================================
def _audit_filter(rows, cols, q, date_from, date_to):
    result = rows
    if q:
        ql = q.lower()
        result = [r for r in result if any(ql in str(r.get(c) or "").lower() for c in cols)]
    if date_from:
        result = [r for r in result if str(r.get("timestamp") or r.get("alert_time") or "") >= date_from]
    if date_to:
        result = [r for r in result if str(r.get("timestamp") or r.get("alert_time") or "") <= date_to + " 23:59:59"]
    return result


@app.route("/audit/activity")
@role_required("admin")
def audit_activity():
    q = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to   = request.args.get("to", "").strip()
    rows = query_all("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 1000")
    cols = ["timestamp", "username", "action", "module", "details", "ip_address"]
    filtered = _audit_filter([dict(r) for r in rows], cols, q, date_from, date_to)
    return render_template("audit.html", title="User Activity Logs", rows=filtered,
                           kind="activity", cols=cols, q=q, date_from=date_from, date_to=date_to)


@app.route("/audit/logins")
@role_required("admin")
def audit_logins():
    q = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to   = request.args.get("to", "").strip()
    rows = query_all("SELECT * FROM login_history ORDER BY id DESC LIMIT 1000")
    cols = ["timestamp", "username", "role", "entry_hash", "status", "ip_address", "user_agent"]
    filtered = _audit_filter([dict(r) for r in rows], cols, q, date_from, date_to)
    return render_template("audit.html", title="Login History", rows=filtered,
                           kind="logins", cols=cols, q=q, date_from=date_from, date_to=date_to)


@app.route("/audit/files")
@role_required("admin")
def audit_files():
    q = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to   = request.args.get("to", "").strip()
    rows = query_all("SELECT * FROM file_access_logs ORDER BY id DESC LIMIT 1000")
    cols = ["timestamp", "username", "filename", "action", "ip_address"]
    filtered = _audit_filter([dict(r) for r in rows], cols, q, date_from, date_to)
    return render_template("audit.html", title="File Access Logs", rows=filtered,
                           kind="files", cols=cols, q=q, date_from=date_from, date_to=date_to)


@app.route("/audit/alerts")
@role_required("admin")
def audit_alerts():
    q = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to   = request.args.get("to", "").strip()
    rows = query_all("SELECT * FROM injection_alerts ORDER BY id DESC LIMIT 1000")
    cols = ["alert_time", "username", "input_field", "payload", "ip_address"]
    filtered = _audit_filter([dict(r) for r in rows], cols, q, date_from, date_to)
    return render_template("audit.html", title="SQL Injection Alerts", rows=filtered,
                           kind="alerts", cols=cols, q=q, date_from=date_from, date_to=date_to)


@app.route("/audit/export/<kind>")
@role_required("admin")
def audit_export(kind):
    try:
        filename, csv_text = fz.export_csv(kind)
    except ValueError:
        abort(404)
    fz.log_activity(request, current_user(), "evidence_export", "forensics", f"kind={kind}")
    return Response(csv_text, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "text/csv",
    })


# ============================================================================
# Notices & Announcements
# ============================================================================
@app.route("/notices")
@login_required
def notices():
    u = current_user()
    if u["role"] == "student":
        rows = query_all(
            "SELECT n.*, u.full_name poster FROM notices n LEFT JOIN users u ON n.posted_by = u.id "
            "WHERE n.target_role IN ('all','student') ORDER BY n.is_pinned DESC, n.id DESC"
        )
    elif u["role"] == "faculty":
        rows = query_all(
            "SELECT n.*, u.full_name poster FROM notices n LEFT JOIN users u ON n.posted_by = u.id "
            "WHERE n.target_role IN ('all','faculty') ORDER BY n.is_pinned DESC, n.id DESC"
        )
    else:
        rows = query_all(
            "SELECT n.*, u.full_name poster FROM notices n LEFT JOIN users u ON n.posted_by = u.id "
            "ORDER BY n.is_pinned DESC, n.id DESC"
        )
    fz.log_activity(request, u, "view", "notices")
    return render_template("notices.html", notices=rows)


@app.route("/notices/new", methods=["POST"])
@role_required("admin", "faculty")
def notice_create():
    title       = (request.form.get("title") or "").strip()
    body        = (request.form.get("body") or "").strip()
    category    = (request.form.get("category") or "general").strip()
    target_role = (request.form.get("target_role") or "all").strip()
    is_pinned   = 1 if request.form.get("is_pinned") else 0
    if not title or not body:
        flash("Title and body are required.", "error")
        return redirect(url_for("notices"))
    execute(
        "INSERT INTO notices (title, body, category, target_role, posted_by, is_pinned) VALUES (?,?,?,?,?,?)",
        (title, body, category, target_role, session["user_id"], is_pinned)
    )
    fz.log_activity(request, current_user(), "create", "notices", f"title={title}")
    flash("Notice posted.", "success")
    return redirect(url_for("notices"))


@app.route("/notices/<int:nid>/delete", methods=["POST"])
@role_required("admin", "faculty")
def notice_delete(nid):
    u = current_user()
    notice = query_one("SELECT * FROM notices WHERE id = ?", (nid,))
    if not notice: abort(404)
    # Faculty can only delete their own; admin can delete any
    if u["role"] == "faculty" and notice["posted_by"] != u["id"]:
        flash("You can only delete your own notices.", "error")
        return redirect(url_for("notices"))
    execute("DELETE FROM notices WHERE id = ?", (nid,))
    fz.log_activity(request, u, "delete", "notices", f"id={nid}")
    flash("Notice deleted.", "success")
    return redirect(url_for("notices"))


# ============================================================================
# Exam Schedule
# ============================================================================
@app.route("/exams")
@login_required
def exam_schedule():
    u = current_user()
    if u["role"] == "student":
        user_db = query_one("SELECT branch, year FROM users WHERE id = ?", (u["id"],))
        rows = query_all(
            "SELECT e.*, us.full_name created_by_name FROM exam_schedule e "
            "LEFT JOIN users us ON e.created_by = us.id "
            "WHERE (e.department IS NULL OR e.department = '' OR e.department = ?) "
            "  AND (e.year IS NULL OR e.year = 0 OR e.year = ?) "
            "ORDER BY e.exam_date ASC, e.exam_time ASC",
            (user_db["branch"] or "", user_db["year"] or 0)
        )
    else:
        rows = query_all(
            "SELECT e.*, us.full_name created_by_name FROM exam_schedule e "
            "LEFT JOIN users us ON e.created_by = us.id "
            "ORDER BY e.exam_date ASC, e.exam_time ASC"
        )
    fz.log_activity(request, u, "view", "exam_schedule")
    return render_template("exam_schedule.html", exams=rows)


@app.route("/exams/new", methods=["POST"])
@role_required("admin", "faculty")
def exam_create():
    subject   = (request.form.get("subject") or "").strip()
    exam_type = (request.form.get("exam_type") or "midterm").strip()
    exam_date = (request.form.get("exam_date") or "").strip()
    exam_time = (request.form.get("exam_time") or "").strip()
    venue     = (request.form.get("venue") or "").strip()
    department = (request.form.get("department") or "").strip()
    year      = request.form.get("year") or None
    duration  = request.form.get("duration_mins") or 180
    if not all([subject, exam_date, exam_time, venue]):
        flash("Subject, date, time and venue are required.", "error")
        return redirect(url_for("exam_schedule"))
    execute(
        "INSERT INTO exam_schedule (subject, exam_type, exam_date, exam_time, venue, "
        "department, year, duration_mins, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (subject, exam_type, exam_date, exam_time, venue, department,
         int(year) if year else None, int(duration), session["user_id"])
    )
    fz.log_activity(request, current_user(), "create", "exam_schedule", f"subject={subject}")
    flash("Exam added to schedule.", "success")
    return redirect(url_for("exam_schedule"))


@app.route("/exams/<int:eid>/delete", methods=["POST"])
@role_required("admin", "faculty")
def exam_delete(eid):
    exam = query_one("SELECT * FROM exam_schedule WHERE id = ?", (eid,))
    if not exam: abort(404)
    execute("DELETE FROM exam_schedule WHERE id = ?", (eid,))
    fz.log_activity(request, current_user(), "delete", "exam_schedule", f"id={eid}")
    flash("Exam removed.", "success")
    return redirect(url_for("exam_schedule"))


# ============================================================================
# Results / Marksheet
# ============================================================================
@app.route("/results")
@login_required
def results():
    u = current_user()
    selected_student = None
    result_rows = []
    semester_summary = []
    students = []

    if u["role"] == "student":
        user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
        selected_student = query_one(
            "SELECT * FROM students WHERE email = ? OR full_name = ?",
            (user_db["email"], user_db["full_name"])
        )
        sid = selected_student["id"] if selected_student else None
    else:
        students = query_all("SELECT id, roll_number, full_name FROM students ORDER BY roll_number")
        sid = request.args.get("student_id") or None
        if sid:
            selected_student = query_one("SELECT * FROM students WHERE id = ?", (sid,))

    sem = request.args.get("sem") or None

    if sid:
        if sem:
            result_rows = query_all(
                "SELECT * FROM results WHERE student_id = ? AND semester = ? ORDER BY subject",
                (sid, int(sem))
            )
        else:
            result_rows = query_all(
                "SELECT * FROM results WHERE student_id = ? ORDER BY semester, subject", (sid,)
            )
        # Semester-wise SGPA summary
        semester_summary = query_all("""
            SELECT semester,
                   COUNT(*) subjects,
                   SUM(COALESCE(credits, 4)) total_credits,
                   ROUND(SUM(grade_points * COALESCE(credits, 4)) / NULLIF(SUM(COALESCE(credits, 4)), 0), 2) AS sgpa,
                   SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) backlogs
            FROM results WHERE student_id = ?
            GROUP BY semester ORDER BY semester
        """, (sid,))
        # CGPA = weighted average across all semesters
        cgpa_row = query_one("""
            SELECT ROUND(
                SUM(grade_points * COALESCE(credits, 4)) /
                NULLIF(SUM(COALESCE(credits, 4)), 0), 2) AS cgpa,
                   SUM(COALESCE(credits, 4)) total_credits
            FROM results WHERE student_id = ?
        """, (sid,))
        cgpa = cgpa_row["cgpa"] if cgpa_row else None

    else:
        cgpa = None
    semesters = list(range(1, 9))
    fz.log_activity(request, u, "view", "results", f"student_id={sid}")
    return render_template("results.html", selected_student=selected_student,
                           result_rows=result_rows, semester_summary=semester_summary,
                           students=students, sid=int(sid) if sid else None,
                           sem=int(sem) if sem else None, semesters=semesters,
                           cgpa=cgpa)


@app.route("/results/post", methods=["POST"])
@role_required("admin", "faculty")
def result_post():
    student_id     = request.form.get("student_id")
    subject        = (request.form.get("subject") or "").strip()
    semester       = request.form.get("semester")
    internal_marks = request.form.get("internal_marks") or 0
    external_marks = request.form.get("external_marks") or 0
    max_marks      = request.form.get("max_marks") or 100
    credits        = request.form.get("credits") or 4
    if not all([student_id, subject, semester]):
        flash("Student, subject and semester are required.", "error")
        return redirect(url_for("results"))
    internal = float(internal_marks)
    external = float(external_marks)
    total    = internal + external
    mx       = float(max_marks)
    pct      = (total / mx) * 100 if mx else 0
    grade_map = [(93,"A+",10),(85,"A",9),(77,"B+",8),(69,"B",7),(61,"C+",6),(53,"C",5),(45,"D",4),(0,"F",0)]
    grade, gp = "F", 0
    for threshold, g, points in grade_map:
        if pct >= threshold:
            grade, gp = g, points
            break
    status = "pass" if total >= mx * 0.45 else "fail"
    execute(
        "INSERT OR REPLACE INTO results (student_id, subject, semester, internal_marks, "
        "external_marks, total_marks, max_marks, grade, grade_points, status, credits, posted_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(student_id), subject, int(semester), internal, external,
         total, mx, grade, gp, status, int(credits), session["user_id"])
    )
    fz.log_activity(request, current_user(), "post_result", "results",
                    f"student={student_id} sem={semester} subj={subject}")
    flash("Result posted successfully.", "success")
    return redirect(url_for("results", student_id=student_id))


@app.route("/results/<int:rid>/delete", methods=["POST"])
@role_required("admin")
def result_delete(rid):
    execute("DELETE FROM results WHERE id = ?", (rid,))
    fz.log_activity(request, current_user(), "delete_result", "results", f"id={rid}")
    flash("Result deleted.", "success")
    return redirect(url_for("results"))


# ============================================================================
# Fee Status
# ============================================================================
@app.route("/fees")
@login_required
def fee_status():
    u = current_user()
    selected_student = None
    fee_rows = []
    students = []

    if u["role"] == "student":
        user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
        selected_student = query_one(
            "SELECT * FROM students WHERE email = ? OR full_name = ?",
            (user_db["email"], user_db["full_name"])
        )
        sid = selected_student["id"] if selected_student else None
    else:
        students = query_all("SELECT id, roll_number, full_name FROM students ORDER BY roll_number")
        sid = request.args.get("student_id") or None
        if sid:
            selected_student = query_one("SELECT * FROM students WHERE id = ?", (sid,))

    if sid:
        fee_rows = query_all(
            "SELECT f.*, u.full_name updated_by_name FROM fee_status f "
            "LEFT JOIN users u ON f.updated_by = u.id "
            "WHERE f.student_id = ? ORDER BY f.semester, f.fee_type",
            (sid,)
        )

    fz.log_activity(request, u, "view", "fees")
    return render_template("fee_status.html", selected_student=selected_student,
                           fee_rows=fee_rows, students=students,
                           sid=int(sid) if sid else None)


@app.route("/fees/update", methods=["POST"])
@role_required("admin")
def fee_update():
    student_id  = request.form.get("student_id")
    semester    = request.form.get("semester")
    fee_type    = (request.form.get("fee_type") or "tuition").strip()
    amount      = request.form.get("amount") or 0
    paid_amount = request.form.get("paid_amount") or 0
    due_date    = (request.form.get("due_date") or "").strip()
    remarks     = (request.form.get("remarks") or "").strip()
    if not all([student_id, semester]):
        flash("Student and semester are required.", "error")
        return redirect(url_for("fee_status"))
    amt  = float(amount)
    paid = float(paid_amount)
    status = "paid" if paid >= amt else ("partial" if paid > 0 else "pending")
    execute(
        "INSERT OR REPLACE INTO fee_status (student_id, semester, fee_type, amount, paid_amount, "
        "due_date, status, remarks, updated_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (int(student_id), int(semester), fee_type, amt, paid, due_date, status, remarks, session["user_id"])
    )
    fz.log_activity(request, current_user(), "update_fee", "fees", f"student={student_id}")
    flash("Fee record updated.", "success")
    return redirect(url_for("fee_status", student_id=student_id))


# ============================================================================
# Grievances
# ============================================================================
@app.route("/grievances")
@login_required
def grievances():
    u = current_user()
    if u["role"] == "student":
        rows = query_all(
            "SELECT g.*, us.full_name responder_name FROM grievances g "
            "LEFT JOIN users us ON g.responded_by = us.id "
            "WHERE g.student_id = ? ORDER BY g.id DESC",
            (u["id"],)
        )
    else:
        rows = query_all(
            "SELECT g.*, u.full_name student_name, us.full_name responder_name "
            "FROM grievances g "
            "JOIN users u ON g.student_id = u.id "
            "LEFT JOIN users us ON g.responded_by = us.id "
            "ORDER BY g.status ASC, g.id DESC"
        )
    fz.log_activity(request, u, "view", "grievances")
    return render_template("grievances.html", grievances=rows)


@app.route("/grievances/new", methods=["POST"])
@role_required("student")
def grievance_submit():
    subject     = (request.form.get("subject") or "").strip()
    description = (request.form.get("description") or "").strip()
    category    = (request.form.get("category") or "academic").strip()
    if not subject or not description:
        flash("Subject and description are required.", "error")
        return redirect(url_for("grievances"))
    execute(
        "INSERT INTO grievances (student_id, subject, description, category) VALUES (?,?,?,?)",
        (session["user_id"], subject, description, category)
    )
    fz.log_activity(request, current_user(), "submit_grievance", "grievances", f"subject={subject}")
    flash("Grievance submitted. You will be notified once reviewed.", "success")
    return redirect(url_for("grievances"))


@app.route("/grievances/<int:gid>/respond", methods=["POST"])
@role_required("admin", "faculty")
def grievance_respond(gid):
    response = (request.form.get("response") or "").strip()
    status   = (request.form.get("status") or "resolved").strip()
    if not response:
        flash("Response cannot be empty.", "error")
        return redirect(url_for("grievances"))
    execute(
        "UPDATE grievances SET response=?, status=?, responded_by=?, responded_at=CURRENT_TIMESTAMP WHERE id=?",
        (response, status, session["user_id"], gid)
    )
    fz.log_activity(request, current_user(), "respond_grievance", "grievances", f"id={gid} status={status}")
    flash("Response submitted.", "success")
    return redirect(url_for("grievances"))


@app.route("/grievances/<int:gid>/close", methods=["POST"])
@role_required("admin")
def grievance_close(gid):
    execute("UPDATE grievances SET status='closed' WHERE id=?", (gid,))
    fz.log_activity(request, current_user(), "close_grievance", "grievances", f"id={gid}")
    flash("Grievance closed.", "success")
    return redirect(url_for("grievances"))


# ============================================================================
# Admin: Bulk Student Registration via CSV
# ============================================================================
@app.route("/students/bulk-upload", methods=["GET", "POST"])
@role_required("admin")
def bulk_upload_students():
    results_log = []
    if request.method == "POST":
        f = request.files.get("csv_file")
        if not f or not f.filename.endswith(".csv"):
            flash("Please upload a valid .csv file.", "error")
            return redirect(url_for("bulk_upload_students"))

        import csv, io
        stream = io.StringIO(f.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.DictReader(stream)

        required_cols = {"roll_number", "full_name", "email", "department", "year"}
        if not reader.fieldnames or not required_cols.issubset(
            {c.strip().lower() for c in reader.fieldnames}
        ):
            flash(
                f"CSV must have columns: {', '.join(required_cols)}. "
                f"Optional: phone, section, semester",
                "error"
            )
            return redirect(url_for("bulk_upload_students"))

        created = skipped = errors = 0
        default_pw = generate_password_hash("Student@123")

        for row in reader:
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            roll  = row.get("roll_number", "")
            name  = row.get("full_name", "")
            email = row.get("email", "").lower()
            dept  = row.get("department", "")
            year  = row.get("year", "1")
            phone = row.get("phone", "")

            if not all([roll, name, email, dept]):
                results_log.append({"roll": roll or "?", "name": name or "?",
                                     "status": "error", "msg": "Missing required field"})
                errors += 1
                continue

            # Validate domain
            if not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
                results_log.append({"roll": roll, "name": name, "status": "error",
                                     "msg": f"Email must be @{ALLOWED_EMAIL_DOMAIN}"})
                errors += 1
                continue

            # Skip if already exists
            if query_one("SELECT id FROM users WHERE email = ?", (email,)):
                results_log.append({"roll": roll, "name": name,
                                     "status": "skipped", "msg": "Email already registered"})
                skipped += 1
                continue
            if query_one("SELECT id FROM students WHERE roll_number = ?", (roll,)):
                results_log.append({"roll": roll, "name": name,
                                     "status": "skipped", "msg": "Roll number already exists"})
                skipped += 1
                continue

            try:
                year_int = int(year)
            except ValueError:
                year_int = 1

            # Create user account
            username = roll.lower().replace(" ", "")
            # ensure username unique
            base = username
            suffix = 1
            while query_one("SELECT id FROM users WHERE username = ?", (username,)):
                username = f"{base}{suffix}"
                suffix += 1

            uid = execute(
                "INSERT INTO users (username, email, password_hash, role, full_name, profile_complete) "
                "VALUES (?, ?, ?, 'student', ?, 1)",
                (username, email, default_pw, name)
            )
            # Create student record
            execute(
                "INSERT INTO students (roll_number, full_name, email, department, year, phone, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (roll, name, email, dept, year_int, phone, session["user_id"])
            )
            results_log.append({"roll": roll, "name": name, "status": "created",
                                 "msg": f"username={username} pw=Student@123"})
            created += 1

        fz.log_activity(request, current_user(), "bulk_upload", "students",
                        f"created={created} skipped={skipped} errors={errors}")
        flash(f"Done — {created} created, {skipped} skipped, {errors} errors.", "success")

    return render_template("bulk_upload.html", results_log=results_log)


@app.route("/students/bulk-upload/template")
@role_required("admin")
def bulk_upload_template():
    """Download a sample CSV template."""
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["roll_number", "full_name", "email", "department", "year", "phone"])
    w.writerow(["22BT1CSE001", "Namita Singh",  "namita001btcse@igdtuw.ac.in",  "CSE", "3", "9876543210"])
    w.writerow(["22BT1CSE002", "Priya Sharma",  "priya002btcse@igdtuw.ac.in",   "CSE", "3", "9876543211"])
    w.writerow(["22BT1IT003",  "Anjali Verma",  "anjali003btit@igdtuw.ac.in",   "IT",  "3", "9876543212"])
    w.writerow(["21BT1ECE004", "Sneha Gupta",   "sneha004btece@igdtuw.ac.in",   "ECE", "4", "9876543213"])
    from flask import Response
    return Response(buf.getvalue(), headers={
        "Content-Disposition": "attachment; filename=student_upload_template.csv",
        "Content-Type": "text/csv"
    })


# ============================================================================
# Courses & Enrollment Management
# ============================================================================
@app.route("/courses")
@role_required("admin", "faculty")
def courses():
    u = current_user()
    if u["role"] == "admin":
        all_courses = query_all("""
            SELECT c.*,
                   u.full_name faculty_name,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id) enrolled_count
            FROM courses c
            LEFT JOIN course_faculty cf ON cf.course_id=c.id
            LEFT JOIN users u ON u.id=cf.faculty_id
            ORDER BY c.department, c.semester, c.name
        """)
        all_faculty = query_all("SELECT id, full_name, username FROM users WHERE role='faculty' ORDER BY full_name")
        all_students = query_all("SELECT id, roll_number, full_name, department, year FROM students ORDER BY roll_number")
    else:
        all_courses = query_all("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id) enrolled_count
            FROM courses c
            JOIN course_faculty cf ON cf.course_id=c.id
            WHERE cf.faculty_id=?
            ORDER BY c.department, c.semester, c.name
        """, (u["id"],))
        all_faculty = []
        all_students = []

    # For each course, get enrolled students (admin detail view)
    course_id = request.args.get("course_id") or None
    enrolled_students = []
    selected_course = None
    if course_id:
        selected_course = query_one("SELECT * FROM courses WHERE id=?", (int(course_id),))
        enrolled_students = query_all(
            "SELECT s.* FROM students s JOIN enrollments e ON e.student_id=s.id "
            "WHERE e.course_id=? ORDER BY s.roll_number",
            (int(course_id),)
        )
    fz.log_activity(request, u, "view", "courses")
    return render_template("courses.html", courses=all_courses, all_faculty=all_faculty,
                           all_students=all_students, enrolled_students=enrolled_students,
                           selected_course=selected_course,
                           course_id=int(course_id) if course_id else None)


@app.route("/courses/new", methods=["POST"])
@role_required("admin")
def course_create():
    name    = (request.form.get("name") or "").strip()
    code    = (request.form.get("code") or "").strip().upper()
    subject = (request.form.get("subject") or "").strip()
    sem     = request.form.get("semester") or 1
    dept    = (request.form.get("department") or "").strip()
    section = (request.form.get("section") or "A").strip().upper()
    yr      = (request.form.get("academic_year") or "2024-25").strip()
    credits = request.form.get("credits") or 4
    faculty_id = request.form.get("faculty_id") or None

    if not all([name, code, subject, dept]):
        flash("Name, code, subject and department are required.", "error")
        return redirect(url_for("courses"))
    if query_one("SELECT id FROM courses WHERE code=?", (code,)):
        flash(f"Course code '{code}' already exists.", "error")
        return redirect(url_for("courses"))

    cid = execute(
        "INSERT INTO courses (name, code, subject, semester, department, section, academic_year, credits, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (name, code, subject, int(sem), dept, section, yr, int(credits), session["user_id"])
    )
    if faculty_id:
        execute("INSERT OR IGNORE INTO course_faculty (course_id, faculty_id) VALUES (?,?)",
                (cid, int(faculty_id)))

    # Auto-enroll matching students (same dept + semester range)
    year = (int(sem) + 1) // 2
    enrolled = query_all(
        "SELECT id FROM students WHERE department=? AND year=?", (dept, year)
    )
    for s in enrolled:
        execute("INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?,?)",
                (cid, s["id"]))

    fz.log_activity(request, current_user(), "create_course", "courses", f"code={code}")
    flash(f"Course '{name}' created and {len(enrolled)} students auto-enrolled.", "success")
    return redirect(url_for("courses"))


@app.route("/courses/<int:cid>/assign-faculty", methods=["POST"])
@role_required("admin")
def course_assign_faculty(cid):
    faculty_id = request.form.get("faculty_id")
    if not faculty_id:
        flash("Select a faculty member.", "error")
        return redirect(url_for("courses", course_id=cid))
    # Remove existing assignment then re-assign
    execute("DELETE FROM course_faculty WHERE course_id=?", (cid,))
    execute("INSERT INTO course_faculty (course_id, faculty_id) VALUES (?,?)",
            (cid, int(faculty_id)))
    fz.log_activity(request, current_user(), "assign_faculty", "courses",
                    f"course={cid} faculty={faculty_id}")
    flash("Faculty assigned.", "success")
    return redirect(url_for("courses", course_id=cid))


@app.route("/courses/<int:cid>/enroll", methods=["POST"])
@role_required("admin")
def course_enroll(cid):
    student_id = request.form.get("student_id")
    if not student_id:
        flash("Select a student.", "error")
        return redirect(url_for("courses", course_id=cid))
    execute("INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?,?)",
            (cid, int(student_id)))
    fz.log_activity(request, current_user(), "enroll_student", "courses",
                    f"course={cid} student={student_id}")
    flash("Student enrolled.", "success")
    return redirect(url_for("courses", course_id=cid))


@app.route("/courses/<int:cid>/unenroll/<int:sid>", methods=["POST"])
@role_required("admin")
def course_unenroll(cid, sid):
    execute("DELETE FROM enrollments WHERE course_id=? AND student_id=?", (cid, sid))
    fz.log_activity(request, current_user(), "unenroll_student", "courses",
                    f"course={cid} student={sid}")
    flash("Student removed from course.", "success")
    return redirect(url_for("courses", course_id=cid))


@app.route("/courses/<int:cid>/delete", methods=["POST"])
@role_required("admin")
def course_delete(cid):
    execute("DELETE FROM courses WHERE id=?", (cid,))
    fz.log_activity(request, current_user(), "delete_course", "courses", f"id={cid}")
    flash("Course deleted.", "success")
    return redirect(url_for("courses"))


@app.route("/courses/<int:cid>/bulk-enroll", methods=["POST"])
@role_required("admin")
def course_bulk_enroll(cid):
    """Enroll all students from a dept+year into a course."""
    course = query_one("SELECT * FROM courses WHERE id=?", (cid,))
    if not course: abort(404)
    year = (course["semester"] + 1) // 2
    students = query_all(
        "SELECT id FROM students WHERE department=? AND year=?",
        (course["department"], year)
    )
    count = 0
    for s in students:
        try:
            execute("INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?,?)",
                    (cid, s["id"]))
            count += 1
        except Exception:
            pass
    fz.log_activity(request, current_user(), "bulk_enroll", "courses",
                    f"course={cid} count={count}")
    flash(f"{count} students bulk-enrolled into {course['name']}.", "success")
    return redirect(url_for("courses", course_id=cid))


# ============================================================================
# Low Attendance Report (admin + faculty)
# ============================================================================
@app.route("/low-attendance")
@role_required("admin", "faculty")
def low_attendance_report():
    low_att = query_all("""
        SELECT s.full_name, s.roll_number, s.department, s.year, att.subject,
               SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) AS present,
               COUNT(*) AS total,
               ROUND(100.0 * SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
        FROM attendance att
        JOIN students s ON s.id = att.student_id
        GROUP BY att.student_id, att.subject
        HAVING pct < 75
        ORDER BY pct ASC
    """)
    fz.log_activity(request, current_user(), "view_low_attendance", "attendance")
    return render_template("low_attendance.html", low_att=low_att)


@app.route("/low-attendance/export")
# ADD THESE 5 SIMPLE ROUTES TO YOUR app.py
# (Place them AFTER low_attendance_export function, BEFORE admin_create_user function)

# ============================================================================
# Syllabus
# ============================================================================
@app.route("/syllabus", methods=["GET"])
@login_required
def syllabus_index():
    return render_template("syllabus_index.html")


@app.route("/syllabus/manage", methods=["GET"])
@role_required("admin")
def syllabus_admin():
    return render_template("syllabus_admin.html")


# ============================================================================
# Course Materials
# ============================================================================
@app.route("/materials", methods=["GET"])
@login_required
def materials_index():
    return render_template("materials_index.html")


# ============================================================================
# Announcements
# ============================================================================
@app.route("/announcements", methods=["GET"])
@login_required
def announcements_index():
    return render_template("announcements_index.html")


# ============================================================================
# Faculty Analytics
# ============================================================================
@app.route("/faculty-analytics", methods=["GET"])
@role_required("faculty")
def faculty_analytics_index():
    return render_template("faculty_analytics_index.html")
@role_required("admin", "faculty")
def low_attendance_export():
    import csv, io
    low_att = query_all("""
        SELECT s.full_name, s.roll_number, s.department, s.year, att.subject,
               SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) AS present,
               COUNT(*) AS total,
               ROUND(100.0 * SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
        FROM attendance att
        JOIN students s ON s.id = att.student_id
        GROUP BY att.student_id, att.subject
        HAVING pct < 75
        ORDER BY pct ASC
    """)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student Name", "Roll No", "Department", "Year", "Subject", "Present", "Total", "Attendance %"])
    for r in low_att:
        w.writerow([r["full_name"], r["roll_number"], r["department"], r["year"],
                    r["subject"], r["present"], r["total"], r["pct"]])
    fz.log_activity(request, current_user(), "export_low_attendance", "attendance")
    return Response(buf.getvalue(), headers={
        "Content-Disposition": 'attachment; filename="low_attendance.csv"',
        "Content-Type": "text/csv",
    })


# ============================================================================
# Admin: create faculty / admin accounts & delete users
# ============================================================================
@app.route("/users/create", methods=["POST"])
@role_required("admin")
def admin_create_user():
    full_name = (request.form.get("full_name") or "").strip()
    username  = (request.form.get("username") or "").strip()
    email     = (request.form.get("email") or "").strip()
    role      = (request.form.get("role") or "").strip()
    password  = request.form.get("password") or ""
    errors = []
    if not full_name: errors.append("Full name is required.")
    if not username:  errors.append("Username is required.")
    if not email:     errors.append("Email is required.")
    if role not in ("faculty", "admin"):
        errors.append("Role must be faculty or admin.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if query_one("SELECT id FROM users WHERE username = ?", (username,)):
        errors.append(f"Username '{username}' is already taken.")
    if query_one("SELECT id FROM users WHERE email = ?", (email,)):
        errors.append(f"Email '{email}' is already registered.")
    if errors:
        for e in errors: flash(e, "error")
        return redirect(url_for("users_list"))
    uid = execute(
        "INSERT INTO users (username, email, password_hash, role, full_name, profile_complete) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (username, email, generate_password_hash(password), role, full_name),
    )
    fz.log_activity(request, current_user(), "admin_create_user", "auth",
                    f"created {role} account: {username}")
    flash(f"{role.capitalize()} account '{username}' created successfully.", "success")
    return redirect(url_for("users_list"))


@app.route("/users/<int:uid>/delete", methods=["POST"])
@role_required("admin")
def admin_delete_user(uid):
    me = current_user()
    if uid == me["id"]:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("users_list"))
    user = query_one("SELECT username, role FROM users WHERE id = ?", (uid,))
    if not user:
        abort(404)
    execute("DELETE FROM users WHERE id = ?", (uid,))
    fz.log_activity(request, current_user(), "admin_delete_user", "auth",
                    f"deleted {user['role']} account: {user['username']}")
    flash(f"Account '{user['username']}' has been deleted.", "success")
    return redirect(url_for("users_list"))


# ============================================================================
# JWT API
# ============================================================================
@app.route("/api/token", methods=["POST"])
@csrf.exempt
def api_token():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = query_one("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
    if user and check_password_hash(user["password_hash"], password):
        return jsonify({"access_token": issue_jwt(user), "token_type": "bearer", "role": user["role"]})
    return jsonify({"error": "Invalid credentials"}), 401


@app.route("/api/students", methods=["GET"])
@csrf.exempt
@jwt_required("admin", "faculty")
def api_students():
    rows = query_all("SELECT id, roll_number, full_name, department, year, cgpa FROM students ORDER BY roll_number")
    return jsonify([dict(r) for r in rows])


@app.route("/api/students/<int:sid>", methods=["GET"])
@csrf.exempt
@jwt_required("admin", "faculty")
def api_student(sid):
    row = query_one("SELECT * FROM students WHERE id = ?", (sid,))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


# ============================================================================
# Attendance — Bulk Marking JSON API (used by attendance_bulk.html's
# hierarchical semester-first UI). Session-based, not JWT, since it's called
# from the logged-in browser session — so it's CSRF-exempt (fetch sends JSON,
# no CSRF token) but still gated by role_required on the normal session cookie.
# ============================================================================
@app.route("/api/courses/by-semester", methods=["GET"])
@csrf.exempt
@role_required("admin", "faculty")
def api_courses_by_semester():
    u = current_user()
    if u["role"] == "faculty":
        rows = query_all(
            "SELECT c.id, c.name, c.code, c.subject, c.semester, c.department, c.section, "
            "(SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id) AS enrolled_count "
            "FROM courses c JOIN course_faculty cf ON cf.course_id = c.id "
            "WHERE cf.faculty_id = ? ORDER BY c.semester, c.name",
            (u["id"],)
        )
    else:
        rows = query_all(
            "SELECT c.id, c.name, c.code, c.subject, c.semester, c.department, c.section, "
            "(SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id) AS enrolled_count "
            "FROM courses c ORDER BY c.semester, c.name"
        )

    grouped = {}
    for r in rows:
        sem = str(r["semester"])
        grouped.setdefault(sem, []).append(dict(r))
    return jsonify(grouped)


@app.route("/api/students/in-course/<int:course_id>", methods=["GET"])
@csrf.exempt
@role_required("admin", "faculty")
def api_students_in_course(course_id):
    u = current_user()
    if u["role"] == "faculty":
        owns = query_one(
            "SELECT 1 FROM course_faculty WHERE course_id = ? AND faculty_id = ?",
            (course_id, u["id"])
        )
        if not owns:
            return jsonify({"error": "Not authorized for this course"}), 403

    rows = query_all(
        "SELECT s.id, s.roll_number, s.full_name, s.department, s.year, s.section "
        "FROM students s JOIN enrollments e ON e.student_id = s.id "
        "WHERE e.course_id = ? ORDER BY s.roll_number",
        (course_id,)
    )
    return jsonify([dict(r) for r in rows])


@app.route("/api/attendance/bulk-mark", methods=["POST"])
@csrf.exempt
@role_required("admin", "faculty")
def api_attendance_bulk_mark():
    u = current_user()
    data = request.get_json(silent=True) or {}
    course_id  = data.get("course_id")
    subject    = (data.get("subject") or "").strip()
    date_val   = (data.get("date") or "").strip()
    attendance = data.get("attendance") or {}

    if not course_id or not subject or not date_val or not attendance:
        return jsonify({"error": "course_id, subject, date, and attendance are required"}), 400

    if u["role"] == "faculty":
        owns = query_one(
            "SELECT 1 FROM course_faculty WHERE course_id = ? AND faculty_id = ?",
            (course_id, u["id"])
        )
        if not owns:
            return jsonify({"error": "Not authorized for this course"}), 403

    count = 0
    for sid, status in attendance.items():
        if status not in ("present", "absent"):
            continue
        try:
            execute(
                "INSERT OR REPLACE INTO attendance (student_id, subject, date, status, marked_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (int(sid), subject, date_val, status, u["id"])
            )
            count += 1
        except Exception:
            pass

    fz.log_activity(request, u, "bulk_attendance", "attendance",
                    f"course_id={course_id} subject={subject} date={date_val} count={count}")
    return jsonify({"count": count})


# ============================================================================
# Attendance — Bulk Marking (mark all present + individual overrides)
# ============================================================================
@app.route("/attendance/bulk-mark", methods=["GET", "POST"])
@role_required("admin", "faculty")
def attendance_bulk_mark():
    u = current_user()
    my_courses = []
    students = []
    course_filter = request.args.get("course_id") or request.form.get("course_id") or None

    if u["role"] == "faculty":
        my_courses = query_all(
            "SELECT c.id, c.name, c.code, c.subject, c.semester, c.department, c.section "
            "FROM courses c JOIN course_faculty cf ON cf.course_id=c.id "
            "WHERE cf.faculty_id=? ORDER BY c.name",
            (u["id"],)
        )
    else:
        my_courses = query_all(
            "SELECT id, name, code, subject, semester, department, section FROM courses ORDER BY name"
        )

    if course_filter:
        course_filter = int(course_filter)
        students = query_all(
            "SELECT s.* FROM students s JOIN enrollments e ON e.student_id=s.id "
            "WHERE e.course_id=? ORDER BY s.roll_number",
            (course_filter,)
        )

    if request.method == "POST":
        subject   = (request.form.get("subject") or "").strip()
        date_val  = (request.form.get("date") or "").strip()
        mark_all  = request.form.get("mark_all_present")
        student_ids = request.form.getlist("student_ids")

        if not subject or not date_val or not student_ids:
            flash("Subject, date, and at least one student are required.", "error")
            return redirect(url_for("attendance_bulk_mark", course_id=course_filter))

        count = 0
        for sid in student_ids:
            # Individual override: check if specific student has override checkbox
            if mark_all:
                # Mark all present unless individually overridden to absent
                override_key = f"override_{sid}"
                status = "absent" if request.form.get(override_key) else "present"
            else:
                # Individual status per student
                status = request.form.get(f"status_{sid}") or "present"
            try:
                execute(
                    "INSERT OR REPLACE INTO attendance (student_id, subject, date, status, marked_by) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (int(sid), subject, date_val, status, u["id"])
                )
                count += 1
            except Exception:
                pass

        fz.log_activity(request, u, "bulk_attendance", "attendance",
                        f"subject={subject} date={date_val} count={count}")
        flash(f"Attendance marked for {count} students.", "success")
        return redirect(url_for("attendance_bulk_mark", course_id=course_filter))

    today = __import__("datetime").date.today().isoformat()
    return render_template("attendance_bulk.html",
                           my_courses=my_courses, students=students,
                           course_filter=course_filter, today=today)


# ============================================================================
# SGPA — Persistence (save/load drafts)
# ============================================================================
@app.route("/sgpa")
@login_required
def sgpa():
    u = current_user()
    sem = request.args.get("sem", 1, type=int)
    drafts = query_all(
        "SELECT * FROM sgpa_drafts WHERE student_id = ? AND semester = ? ORDER BY subject",
        (u["id"], sem)
    )
    return render_template("sgpa.html", drafts=drafts, sem=sem)


@app.route("/sgpa/save", methods=["POST"])
@login_required
def sgpa_save():
    u = current_user()
    sem      = request.form.get("semester", type=int) or 1
    subjects = request.form.getlist("subject[]")
    grades   = request.form.getlist("grade[]")
    credits  = request.form.getlist("credits[]")

    # Clear existing drafts for this semester
    execute("DELETE FROM sgpa_drafts WHERE student_id = ? AND semester = ?", (u["id"], sem))
    saved = 0
    for subj, grade, cred in zip(subjects, grades, credits):
        subj = subj.strip()
        if not subj:
            continue
        try:
            execute(
                "INSERT OR REPLACE INTO sgpa_drafts (student_id, semester, subject, grade, credits) "
                "VALUES (?, ?, ?, ?, ?)",
                (u["id"], sem, subj, grade, int(cred) or 4)
            )
            saved += 1
        except Exception:
            pass
    flash(f"Saved {saved} subjects for Semester {sem}.", "success")
    return redirect(url_for("sgpa", sem=sem))


# ============================================================================
# Timetable / Class Schedule
# ============================================================================
@app.route("/timetable")
@login_required
def timetable():
    u = current_user()
    dept = request.args.get("dept") or None
    sem  = request.args.get("sem", type=int) or None
    section = request.args.get("section", "A")

    if u["role"] == "student":
        user_db = query_one("SELECT branch, year FROM users WHERE id = ?", (u["id"],))
        dept    = user_db["branch"] or dept
        year    = user_db["year"] or 1
        sem     = (year - 1) * 2 + 1  # current semester
        rows = query_all(
            "SELECT t.*, u.full_name faculty_name FROM timetable t "
            "LEFT JOIN users u ON u.id = t.faculty_id "
            "WHERE t.department = ? AND t.semester = ? AND t.section = ? "
            "ORDER BY CASE t.day_of_week "
            "  WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 "
            "  WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END, t.start_time",
            (dept, sem, section)
        )
        departments, semesters = [], []
    elif u["role"] == "faculty":
        rows = query_all(
            "SELECT t.*, u.full_name faculty_name FROM timetable t "
            "LEFT JOIN users u ON u.id = t.faculty_id "
            "WHERE t.faculty_id = ? "
            "ORDER BY CASE t.day_of_week "
            "  WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 "
            "  WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END, t.start_time",
            (u["id"],)
        )
        departments, semesters = [], []
    else:
        # Admin — filterable
        base_q = (
            "SELECT t.*, u.full_name faculty_name FROM timetable t "
            "LEFT JOIN users u ON u.id = t.faculty_id WHERE 1=1"
        )
        params = []
        if dept:
            base_q += " AND t.department = ?"
            params.append(dept)
        if sem:
            base_q += " AND t.semester = ?"
            params.append(sem)
        base_q += (
            " ORDER BY CASE t.day_of_week "
            "  WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 "
            "  WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END, t.start_time"
        )
        rows = query_all(base_q, params)
        departments = [r["department"] for r in
                       query_all("SELECT DISTINCT department FROM timetable ORDER BY department")]
        semesters = [r["semester"] for r in
                     query_all("SELECT DISTINCT semester FROM timetable ORDER BY semester")]

    # Group by day
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    schedule = {day: [] for day in days_order}
    for r in rows:
        day = r["day_of_week"]
        if day in schedule:
            schedule[day].append(r)

    all_faculty = query_all(
        "SELECT id, full_name FROM users WHERE role='faculty' ORDER BY full_name"
    ) if u["role"] == "admin" else []

    fz.log_activity(request, u, "view", "timetable")
    return render_template("timetable.html", schedule=schedule, days_order=days_order,
                           departments=departments, semesters=semesters,
                           dept=dept, sem=sem, section=section,
                           all_faculty=all_faculty)


@app.route("/timetable/new", methods=["POST"])
@role_required("admin", "faculty")
def timetable_create():
    u = current_user()
    dept      = (request.form.get("department") or "").strip()
    sem       = request.form.get("semester") or 1
    section   = (request.form.get("section") or "A").strip().upper()
    day       = (request.form.get("day_of_week") or "").strip()
    start     = (request.form.get("start_time") or "").strip()
    end       = (request.form.get("end_time") or "").strip()
    room      = (request.form.get("room") or "").strip()
    subject   = (request.form.get("subject") or "").strip()
    faculty_id = request.form.get("faculty_id") or u["id"]
    acad_year = (request.form.get("academic_year") or "2024-25").strip()

    if not all([dept, day, start, end, subject]):
        flash("Department, day, times and subject are required.", "error")
        return redirect(url_for("timetable"))

    execute(
        "INSERT INTO timetable (department, semester, section, day_of_week, start_time, "
        "end_time, room, faculty_id, subject, academic_year, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (dept, int(sem), section, day, start, end, room,
         int(faculty_id), subject, acad_year, u["id"])
    )
    fz.log_activity(request, u, "create_timetable", "timetable", f"{dept} sem{sem} {day} {subject}")
    flash("Timetable entry added.", "success")
    return redirect(url_for("timetable", dept=dept, sem=sem))


@app.route("/timetable/<int:tid>/delete", methods=["POST"])
@role_required("admin", "faculty")
def timetable_delete(tid):
    execute("DELETE FROM timetable WHERE id = ?", (tid,))
    fz.log_activity(request, current_user(), "delete_timetable", "timetable", f"id={tid}")
    flash("Timetable entry removed.", "success")
    return redirect(url_for("timetable"))


# ============================================================================
# Student Analytics Dashboard
# ============================================================================
@app.route("/analytics")
@login_required
def student_analytics():
    u = current_user()
    student = None
    att_trend = []
    sgpa_progression = []
    pending_assignments = 0
    leave_count = 0
    subject_breakdown = []
    heatmap = {}

    # ── Filter context for admin / faculty ───────────────────────────────
    filter_dept    = (request.args.get("dept")    or "").strip()
    filter_sem     = request.args.get("sem",    type=int)
    filter_section = (request.args.get("section") or "").strip()
    filter_course  = request.args.get("course_id", type=int)

    # Available filter options (populated for admin/faculty)
    all_departments = []
    all_semesters   = []
    all_sections    = []
    all_courses     = []
    filter_label    = ""      # human-readable context string shown in the heading

    # ── STUDENT ──────────────────────────────────────────────────────────
    if u["role"] == "student":
        user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
        student = (
            query_one("SELECT * FROM students WHERE user_id = ?", (u["id"],)) or
            query_one("SELECT * FROM students WHERE email = ?", (user_db["email"],))
        )
        if student:
            att_trend = list(reversed(query_all("""
                SELECT strftime('%Y-W%W', date) AS week,
                       ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct,
                       COUNT(*) total
                FROM attendance WHERE student_id = ?
                GROUP BY week ORDER BY week DESC LIMIT 8
            """, (student["id"],))))

            sgpa_progression = query_all("""
                SELECT semester,
                       ROUND(SUM(grade_points * COALESCE(credits,4)) /
                             NULLIF(SUM(COALESCE(credits,4)), 0), 2) AS sgpa
                FROM results WHERE student_id = ?
                GROUP BY semester ORDER BY semester
            """, (student["id"],))

            subject_breakdown = query_all("""
                SELECT subject,
                       ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
                FROM attendance WHERE student_id = ?
                GROUP BY subject ORDER BY subject
            """, (student["id"],))

            user_db2 = query_one("SELECT branch, year FROM users WHERE id = ?", (u["id"],))
            total_asgn = query_one(
                "SELECT COUNT(*) c FROM assignments "
                "WHERE (department IS NULL OR department='' OR department=?) "
                "  AND (year IS NULL OR year=0 OR year=?)",
                (user_db2["branch"] or "", user_db2["year"] or 0)
            )["c"]
            submitted = query_one(
                "SELECT COUNT(*) c FROM homework_submissions WHERE student_id=?",
                (student["id"],)
            )["c"]
            pending_assignments = max(0, total_asgn - submitted)

            # Heatmap
            raw = query_all(
                "SELECT date, status FROM attendance WHERE student_id=? "
                "AND date >= date('now', '-365 days') ORDER BY date",
                (student["id"],)
            )
            from collections import defaultdict
            daily = defaultdict(list)
            for r in raw:
                daily[r["date"]].append(r["status"])
            for ds, statuses in daily.items():
                heatmap[ds] = "present" if any(s == "present" for s in statuses) else "absent"

        leave_count = query_one(
            "SELECT COUNT(*) c FROM leave_applications WHERE student_id=?", (u["id"],)
        )["c"]

    # ── ADMIN / FACULTY ──────────────────────────────────────────────────
    else:
        # Build dropdown options
        all_departments = [r["department"] for r in query_all(
            "SELECT DISTINCT department FROM students WHERE department != '' ORDER BY department"
        )]
        all_semesters = list(range(1, 9))
        all_sections  = [r["section"] for r in query_all(
            "SELECT DISTINCT section FROM students WHERE section != '' ORDER BY section"
        )]

        if u["role"] == "faculty":
            all_courses = query_all(
                "SELECT c.id, c.name, c.code, c.department, c.semester, c.section "
                "FROM courses c JOIN course_faculty cf ON cf.course_id=c.id "
                "WHERE cf.faculty_id=? ORDER BY c.department, c.semester, c.name",
                (u["id"],)
            )
        else:
            all_courses = query_all(
                "SELECT id, name, code, department, semester, section FROM courses "
                "ORDER BY department, semester, name"
            )

        # Build WHERE clause dynamically based on filters
        # We filter attendance by matching students
        student_filter_sql = "1=1"
        student_params = []

        if filter_course:
            # Filter to students in a specific course
            course_info = query_one("SELECT * FROM courses WHERE id=?", (filter_course,))
            if course_info:
                filter_label = f"{course_info['name']} ({course_info['code']}) — {course_info['department']} Sem {course_info['semester']} Sec {course_info['section']}"
            student_filter_sql = "student_id IN (SELECT student_id FROM enrollments WHERE course_id=?)"
            student_params = [filter_course]
        else:
            parts, params = [], []
            if filter_dept:
                parts.append("s.department=?"); params.append(filter_dept)
            if filter_sem:
                year_from_sem = (filter_sem + 1) // 2
                parts.append("s.year=?"); params.append(year_from_sem)
            if filter_section:
                parts.append("s.section=?"); params.append(filter_section)

            if parts:
                sid_rows = query_all(
                    f"SELECT id FROM students s WHERE {' AND '.join(parts)}", params
                )
                sid_list = [r["id"] for r in sid_rows]
                if sid_list:
                    placeholders = ",".join("?" * len(sid_list))
                    student_filter_sql = f"student_id IN ({placeholders})"
                    student_params = sid_list
                else:
                    # No matching students → empty results
                    student_filter_sql = "1=0"
                    student_params = []

                label_parts = []
                if filter_dept:    label_parts.append(filter_dept)
                if filter_sem:     label_parts.append(f"Sem {filter_sem}")
                if filter_section: label_parts.append(f"Section {filter_section}")
                filter_label = " · ".join(label_parts) if label_parts else ""
            else:
                filter_label = "All Students (University-wide)"

        # Faculty: restrict to own courses unless a course filter is set
        if u["role"] == "faculty" and not filter_course and student_filter_sql == "1=1":
            student_filter_sql = (
                "student_id IN (SELECT student_id FROM enrollments e "
                "JOIN course_faculty cf ON cf.course_id=e.course_id WHERE cf.faculty_id=?)"
            )
            student_params = [u["id"]]
            filter_label = "My Students (All Courses)"

        # Attendance trend (weekly %)
        att_trend = list(reversed(query_all(f"""
            SELECT strftime('%Y-W%W', date) AS week,
                   ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct,
                   COUNT(DISTINCT student_id) student_count,
                   COUNT(*) total
            FROM attendance
            WHERE {student_filter_sql}
            GROUP BY week ORDER BY week DESC LIMIT 8
        """, student_params)))

        # Subject-wise breakdown
        subject_breakdown = query_all(f"""
            SELECT subject,
                   ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct,
                   COUNT(DISTINCT student_id) student_count
            FROM attendance
            WHERE {student_filter_sql}
            GROUP BY subject ORDER BY subject
        """, student_params)

        # Top defaulters in this filter
        top_defaulters = query_all(f"""
            SELECT s.full_name, s.roll_number, s.department,
                   att.subject,
                   ROUND(100.0 * SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct,
                   COUNT(*) total
            FROM attendance att
            JOIN students s ON s.id = att.student_id
            WHERE {student_filter_sql.replace('student_id', 'att.student_id')}
            GROUP BY att.student_id, att.subject
            HAVING pct < 75
            ORDER BY pct ASC
            LIMIT 10
        """, student_params)

        # Summary stats
        total_students_in_filter = query_one(f"""
            SELECT COUNT(DISTINCT student_id) c FROM attendance
            WHERE {student_filter_sql}
        """, student_params)["c"]

        overall_pct = query_one(f"""
            SELECT ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1) AS pct
            FROM attendance WHERE {student_filter_sql}
        """, student_params)["pct"]

        pending_assignments = query_one(
            "SELECT COUNT(*) c FROM assignments WHERE due_date >= date('now')"
        )["c"]

        # Heatmap (daily class-wide avg)
        raw = query_all(f"""
            SELECT date,
                   ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 0) AS pct
            FROM attendance
            WHERE {student_filter_sql} AND date >= date('now', '-365 days')
            GROUP BY date ORDER BY date
        """, student_params)
        for r in raw:
            pct = r["pct"] or 0
            heatmap[r["date"]] = "high" if pct >= 75 else ("mid" if pct >= 50 else "low")

        fz.log_activity(request, u, "view", "analytics",
                        f"filter={filter_label}")

        # sqlite3.Row isn't JSON-serializable — the template does
        # `{{ att_trend | tojson }}` for the Chart.js click handler, so
        # convert every Row list to plain dicts before rendering.
        att_trend        = [dict(r) for r in att_trend]
        subject_breakdown = [dict(r) for r in subject_breakdown]
        top_defaulters    = [dict(r) for r in top_defaulters]
        all_courses       = [dict(r) for r in all_courses]

        return render_template("student_analytics.html",
                               student=None,
                               att_trend=att_trend,
                               sgpa_progression=[],
                               pending_assignments=pending_assignments,
                               leave_count=0,
                               subject_breakdown=subject_breakdown,
                               heatmap=heatmap,
                               # Admin/faculty extras
                               filter_label=filter_label,
                               filter_dept=filter_dept,
                               filter_sem=filter_sem,
                               filter_section=filter_section,
                               filter_course=filter_course,
                               all_departments=all_departments,
                               all_semesters=all_semesters,
                               all_sections=all_sections,
                               all_courses=all_courses,
                               overall_pct=overall_pct,
                               total_students_in_filter=total_students_in_filter,
                               top_defaulters=top_defaulters)

    fz.log_activity(request, u, "view", "analytics")

    # Same Row → dict conversion for the student-facing branch.
    att_trend         = [dict(r) for r in att_trend]
    sgpa_progression  = [dict(r) for r in sgpa_progression]
    subject_breakdown = [dict(r) for r in subject_breakdown]

    return render_template("student_analytics.html",
                           student=student,
                           att_trend=att_trend,
                           sgpa_progression=sgpa_progression,
                           pending_assignments=pending_assignments,
                           leave_count=leave_count,
                           subject_breakdown=subject_breakdown,
                           heatmap=heatmap,
                           filter_label="",
                           filter_dept="", filter_sem=None,
                           filter_section="", filter_course=None,
                           all_departments=[], all_semesters=[],
                           all_sections=[], all_courses=[],
                           overall_pct=None,
                           total_students_in_filter=0,
                           top_defaulters=[])


# ============================================================================
# Leave Applications
# ============================================================================
@app.route("/leaves")
@login_required
def leaves():
    u = current_user()
    if u["role"] == "student":
        rows = query_all(
            "SELECT l.*, u.full_name reviewer_name FROM leave_applications l "
            "LEFT JOIN users u ON l.reviewed_by = u.id "
            "WHERE l.student_id = ? ORDER BY l.id DESC",
            (u["id"],)
        )
        faculty_list = query_all(
            "SELECT id, full_name FROM users WHERE role='faculty' ORDER BY full_name"
        )
        return render_template("leaves.html", leaves=rows, faculty_list=faculty_list)
    else:
        rows = query_all(
            "SELECT l.*, us.full_name student_name, uf.full_name reviewer_name "
            "FROM leave_applications l "
            "JOIN users us ON l.student_id = us.id "
            "LEFT JOIN users uf ON l.reviewed_by = uf.id "
            "ORDER BY l.status ASC, l.id DESC"
        )
        return render_template("leaves.html", leaves=rows, faculty_list=[])


@app.route("/leaves/apply", methods=["POST"])
@role_required("student")
def leave_apply():
    u = current_user()
    faculty_id  = request.form.get("faculty_id") or None
    subject     = (request.form.get("subject") or "").strip()
    leave_type  = (request.form.get("leave_type") or "medical").strip()
    from_date   = (request.form.get("from_date") or "").strip()
    to_date     = (request.form.get("to_date") or "").strip()
    reason      = (request.form.get("reason") or "").strip()
    if not all([from_date, to_date, reason]):
        flash("From date, to date and reason are required.", "error")
        return redirect(url_for("leaves"))
    execute(
        "INSERT INTO leave_applications (student_id, faculty_id, subject, leave_type, "
        "from_date, to_date, reason) VALUES (?,?,?,?,?,?,?)",
        (u["id"], int(faculty_id) if faculty_id else None,
         subject, leave_type, from_date, to_date, reason)
    )
    fz.log_activity(request, u, "leave_apply", "leaves", f"from={from_date} to={to_date}")
    flash("Leave application submitted.", "success")
    return redirect(url_for("leaves"))


@app.route("/leaves/<int:lid>/review", methods=["POST"])
@role_required("admin", "faculty")
def leave_review(lid):
    status  = (request.form.get("status") or "approved").strip()
    remark  = (request.form.get("faculty_remark") or "").strip()
    execute(
        "UPDATE leave_applications SET status=?, faculty_remark=?, reviewed_by=?, "
        "reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, remark, session["user_id"], lid)
    )
    fz.log_activity(request, current_user(), "leave_review", "leaves",
                    f"id={lid} status={status}")
    flash(f"Leave application {status}.", "success")
    return redirect(url_for("leaves"))


# ============================================================================
# Error handlers
# ============================================================================
@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="That page or record doesn't exist."), 404

@app.errorhandler(413)
def too_large(_):
    return render_template("error.html", code=413, message="That file is larger than the 5 MB limit."), 413

@app.errorhandler(429)
def rate_limited(_):
    return render_template("error.html", code=429, message="Too many requests. Please wait a moment."), 429

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You don't have permission to access this page."), 403


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)