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
from datetime import date, timedelta
from fee_due_notification import check_fee_due_dates 
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
db.seed()
db.seed_extras()
db.seed_courses()


@app.context_processor
def inject_user():
    u = current_user()
    unread_notices = 0
    try:
        if u and u.get("role") == "student":
            row = query_one(
                "SELECT COUNT(*) c FROM notices "
                "WHERE category='fee' AND target_role IN ('all','student')"
            )
            unread_notices = row["c"] if row else 0
    except Exception:
        unread_notices = 0
    return {"user": u, "config": Config, "unread_notices": unread_notices}


# ============================================================================
# Auth
# ============================================================================
@app.route("/")
def index():
    u = current_user()
    if not u:
        return redirect(url_for("login"))
    if u["role"] == "student":
        return redirect(url_for("student_dashboard"))
    return redirect(url_for("dashboard"))


ALLOWED_EMAIL_DOMAIN = "igdtuw.ac.in"

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        form_data = request.form.copy()
        if form_data.get("role") not in (None, "", "student"):
            flash("Only student accounts can be created via self-registration.", "error")
            return render_template("register.html", form=request.form)

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

        existing_student = query_one(
            "SELECT id FROM students WHERE email = ?", (cleaned["email"],)
        )
        if not existing_student:
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
            if not user["profile_complete"]:
                return redirect(url_for("profile_setup"))
            if user["role"] == "student":
                return redirect(url_for("student_dashboard"))
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
            return redirect(url_for("student_dashboard"))
        return redirect(url_for("dashboard"))
    return render_template("profile_setup.html", user=user, form={})


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    ) if u["role"] == "student" else None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_info":
            full_name         = (request.form.get("full_name") or "").strip()
            contact_no        = (request.form.get("contact_no") or "").strip()
            branch            = (request.form.get("branch") or "").strip()
            university        = (request.form.get("university") or "").strip()
            year              = request.form.get("year") or None
            address           = (request.form.get("address") or "").strip()
            dob               = (request.form.get("dob") or "").strip()
            guardian_name     = (request.form.get("guardian_name") or "").strip()
            emergency_contact = (request.form.get("emergency_contact") or "").strip()
            execute(
                "UPDATE users SET full_name=?, contact_no=?, branch=?, university=?, year=?, "
                "address=?, dob=?, guardian_name=?, emergency_contact=? WHERE id=?",
                (full_name, contact_no, branch, university,
                 int(year) if year else None,
                 address, dob, guardian_name, emergency_contact, u["id"]),
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
    return render_template("profile.html", user_db=user_db, student=student)


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
        selected_student = query_one("SELECT * FROM students WHERE email = ?", (user_db["email"],))
        if not selected_student:
            selected_student = query_one("SELECT * FROM students WHERE full_name = ?", (user_db["full_name"],))
        sid = selected_student["id"] if selected_student else None
        students = []
    elif u["role"] == "faculty":
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

    from datetime import date as _date_att
    return render_template("attendance.html", students=students,
                           selected_student=selected_student,
                           att_data=att_data, low_subjects=low_subjects,
                           sid=int(sid) if sid else None,
                           my_courses=my_courses, course_filter=course_filter,
                           now_date=_date_att.today().isoformat())


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
# SGPA Calculator
# ============================================================================
@app.route("/sgpa")
@login_required
def sgpa():
    return render_template("sgpa.html")


# ============================================================================
# Assignments (faculty upload) & Homework (student upload)
# ============================================================================
def _allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


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
        user_db = query_one("SELECT branch, year FROM users WHERE id = ?", (u["id"],))
        rows = query_all(
            "SELECT a.*, u.full_name uploader_name FROM assignments a "
            "LEFT JOIN users u ON a.uploaded_by = u.id "
            "WHERE (a.department IS NULL OR a.department = ? OR a.department = '') "
            "  AND (a.year IS NULL OR a.year = 0 OR a.year = ?) "
            "ORDER BY a.id DESC",
            (user_db["branch"] or "", user_db["year"] or 0)
        )

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
    if not f or f.filename == "": errors.append("Please attach a file.")
    elif not _allowed_file(f.filename): errors.append("File type not allowed.")
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
    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Please attach your homework file.", "error")
        return redirect(url_for("assignments"))
    if not _allowed_file(f.filename):
        flash("File type not allowed.", "error")
        return redirect(url_for("assignments"))
    safe_name = secure_filename(f.filename)
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    f.save(os.path.join(Config.UPLOAD_DIR, stored_name))
    try:
        execute(
            "INSERT OR REPLACE INTO homework_submissions (assignment_id, student_id, stored_name, original_name) "
            "VALUES (?, ?, ?, ?)",
            (aid, student["id"], stored_name, safe_name)
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
        if q:
            rows = query_all(
                f"SELECT * FROM students WHERE roll_number LIKE ? OR full_name LIKE ? OR email LIKE ? ORDER BY {col} {dir_}",
                (f"%{q}%", f"%{q}%", f"%{q}%"),
            )
        else:
            rows = query_all(f"SELECT * FROM students ORDER BY {col} {dir_}")
        my_courses = []
    elif u["role"] == "faculty":
        my_courses = query_all(
            "SELECT c.id, c.name, c.code, c.subject, c.semester, c.department, c.section, c.academic_year "
            "FROM courses c JOIN course_faculty cf ON cf.course_id=c.id "
            "WHERE cf.faculty_id=? ORDER BY c.department, c.semester, c.name",
            (u["id"],)
        )
        course_filter = request.args.get("course_id") or None
        if course_filter:
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

        # Auto-create a login account for the student
        # Username = email prefix (before @), password = roll number
        auto_username = cleaned["email"].split("@")[0].lower()
        auto_password = cleaned["roll_number"]
        existing_user = query_one("SELECT id FROM users WHERE username = ? OR email = ?",
                                  (auto_username, cleaned["email"]))
        if not existing_user:
            execute(
                "INSERT INTO users (username, email, password_hash, role, full_name, profile_complete) "
                "VALUES (?, ?, ?, 'student', ?, 1)",
                (auto_username, cleaned["email"],
                 generate_password_hash(auto_password),
                 cleaned["full_name"]),
            )
            flash(
                f"Student added. Login credentials — "
                f"Username: {auto_username} | Password: {auto_password} "
                f"(share this with the student)",
                "success"
            )
        else:
            flash("Student added. (A login account with this email already exists.)", "success")

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
    if not _allowed_file(f.filename):
        flash("File type not allowed.", "error")
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
        # Look up student record via users table email
        user_db = query_one("SELECT email FROM users WHERE id = ?", (u["id"],))
        student_db = query_one("SELECT department, year FROM students WHERE email = ?",
                               (user_db["email"],)) if user_db else None
        if student_db:
            dept = student_db["department"] or ""
            year = student_db["year"] or 0
        else:
            dept = ""
            year = 0
        rows = query_all(
            "SELECT e.*, us.full_name created_by_name FROM exam_schedule e "
            "LEFT JOIN users us ON e.created_by = us.id "
            "WHERE (e.department IS NULL OR e.department = '' OR e.department = ?) "
            "  AND (e.year IS NULL OR e.year = 0 OR e.year = ?) "
            "ORDER BY e.exam_date ASC, e.exam_time ASC",
            (dept, year)
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
    subject    = (request.form.get("subject") or "").strip()
    exam_type  = (request.form.get("exam_type") or "midterm").strip()
    exam_date  = (request.form.get("exam_date") or "").strip()
    exam_time  = (request.form.get("exam_time") or "").strip()
    venue      = (request.form.get("venue") or "").strip()
    department = (request.form.get("department") or "").strip()
    year       = request.form.get("year") or None
    duration   = request.form.get("duration_mins") or 180
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
        semester_summary = query_all("""
            SELECT semester,
                   COUNT(*) subjects,
                   ROUND(SUM(grade_points * 1.0) / COUNT(*), 2) AS sgpa,
                   SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) backlogs
            FROM results WHERE student_id = ?
            GROUP BY semester ORDER BY semester
        """, (sid,))

    semesters = list(range(1, 9))
    fz.log_activity(request, u, "view", "results", f"student_id={sid}")
    return render_template("results.html", selected_student=selected_student,
                           result_rows=result_rows, semester_summary=semester_summary,
                           students=students, sid=int(sid) if sid else None,
                           sem=int(sem) if sem else None, semesters=semesters)


@app.route("/results/post", methods=["POST"])
@role_required("admin", "faculty")
def result_post():
    student_id     = request.form.get("student_id")
    subject        = (request.form.get("subject") or "").strip()
    semester       = request.form.get("semester")
    internal_marks = request.form.get("internal_marks") or 0
    external_marks = request.form.get("external_marks") or 0
    max_marks      = request.form.get("max_marks") or 100
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
        "external_marks, total_marks, max_marks, grade, grade_points, status, posted_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (int(student_id), subject, int(semester), internal, external,
         total, mx, grade, gp, status, session["user_id"])
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
    today            = date.today()          
    due_soon         = []                    
    student_due_soon = []                    


    if sid:
        fee_rows = query_all(
            "SELECT f.*, u.full_name updated_by_name FROM fee_status f "
            "LEFT JOIN users u ON f.updated_by = u.id "
            "WHERE f.student_id = ? ORDER BY f.semester, f.fee_type",
            (sid,)
        )
        fee_rows = [dict(row) for row in fee_rows]

        from datetime import datetime

        for f in fee_rows:

    # Add a default value
            f["is_soon"] = False

            if f["due_date"] and f["status"] in ("pending", "partial"):

                d = datetime.strptime(str(f["due_date"]), "%Y-%m-%d").date()

                days_left = (d - today).days

                balance = f["amount"] - f["paid_amount"]

                if 0 <= days_left <= 2 and balance > 0:

                   f["is_soon"] = True

                   student_due_soon.append({
                        "fee_type": f["fee_type"],
                        "semester": f["semester"],
                        "balance": balance,
                        "due_date": f["due_date"],   # Keep it as string
                        "days_left": days_left,
                    })

        if u["role"] == "admin":
            check_fee_due_dates(db, None, None, None, None)
            due_soon = student_due_soon                               
    fz.log_activity(request, u, "view", "fees")
   
    return render_template("fee_status.html", selected_student=selected_student,
                           fee_rows=fee_rows, students=students,
                           sid=int(sid) if sid else None,
                           due_soon=due_soon,                
                           student_due_soon=student_due_soon,
                           today=today,                      
                           )
@app.route("/fees/send-reminders", methods=["POST"])
@role_required("admin")
def send_fee_reminders():
    count = check_fee_due_dates(db, None, None, None, None)
    flash(f"{count} fee reminder notification(s) sent.", "success")
    return redirect(url_for("fee_status"))

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

            if not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
                results_log.append({"roll": roll, "name": name, "status": "error",
                                     "msg": f"Email must be @{ALLOWED_EMAIL_DOMAIN}"})
                errors += 1
                continue

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

            username = roll.lower().replace(" ", "")
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
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["roll_number", "full_name", "email", "department", "year", "phone"])
    w.writerow(["22BT1CSE001", "Namita Singh",  "namita001btcse@igdtuw.ac.in",  "CSE", "3", "9876543210"])
    w.writerow(["22BT1CSE002", "Priya Sharma",  "priya002btcse@igdtuw.ac.in",   "CSE", "3", "9876543211"])
    w.writerow(["22BT1IT003",  "Anjali Verma",  "anjali003btit@igdtuw.ac.in",   "IT",  "3", "9876543212"])
    w.writerow(["21BT1ECE004", "Sneha Gupta",   "sneha004btece@igdtuw.ac.in",   "ECE", "4", "9876543213"])
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
# Low Attendance Report
# ============================================================================
@app.route("/low-attendance")
@role_required("admin", "faculty")
def low_attendance_report():
    low_att = query_all("""
        SELECT s.full_name, s.roll_number, s.email, s.department, s.year, att.subject,
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


@app.route("/low-attendance/email", methods=["POST"])
@csrf.exempt
@role_required("admin", "faculty")
def low_attendance_email():
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    data = request.get_json(force=True) or {}
    subject_line  = (data.get("subject") or "Attendance Warning — Action Required").strip()
    body_template = (data.get("body") or "").strip()
    roll_numbers  = data.get("roll_numbers")

    low_att = query_all("""
        SELECT s.full_name, s.roll_number, s.email, s.department, s.year, att.subject,
               ROUND(100.0 * SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
        FROM attendance att
        JOIN students s ON s.id = att.student_id
        GROUP BY att.student_id, att.subject
        HAVING pct < 75
        ORDER BY pct ASC
    """)

    from collections import defaultdict
    students_map = defaultdict(lambda: {"subjects": [], "email": "", "name": "", "dept": "", "year": ""})
    for r in low_att:
        roll = r["roll_number"]
        if roll_numbers and roll not in roll_numbers:
            continue
        students_map[roll]["email"] = r["email"]
        students_map[roll]["name"]  = r["full_name"]
        students_map[roll]["dept"]  = r["department"]
        students_map[roll]["year"]  = r["year"]
        students_map[roll]["subjects"].append({"subject": r["subject"], "pct": r["pct"]})

    if not students_map:
        return jsonify({"success": False, "message": "No matching students found."}), 400

    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

    if not SMTP_USER or not SMTP_PASS:
        sent = []
        for roll, info in students_map.items():
            subject_list = ", ".join(f"{s['subject']} ({s['pct']}%)" for s in info["subjects"])
            app.logger.info(
                f"[DEV EMAIL] To: {info['email']} | Subject: {subject_line} | "
                f"Student: {info['name']} | Low subjects: {subject_list}"
            )
            sent.append(info["email"])
        fz.log_activity(request, current_user(), "email_low_attendance",
                        "attendance", f"dev_mode count={len(sent)}")
        return jsonify({"success": True, "sent": len(sent),
                        "message": f"Dev mode: {len(sent)} email(s) logged to console (SMTP not configured)."})

    sent, failed = [], []
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        for roll, info in students_map.items():
            try:
                subject_list_html = "".join(
                    f"<li><strong>{s['subject']}</strong> — {s['pct']}%</li>"
                    for s in info["subjects"]
                )
                html_body = body_template.replace("\n", "<br>") if body_template else f"""
                    <p>Dear <strong>{info['name']}</strong>,</p>
                    <p>Your attendance in the following subject(s) is below the required <strong>75%</strong> threshold:</p>
                    <ul>{subject_list_html}</ul>
                    <p>Please ensure regular attendance to avoid academic penalties.</p>
                    <p>Regards,<br>Academic Administration<br>{info['dept']} Department</p>
                """
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject_line
                msg["From"]    = SMTP_FROM
                msg["To"]      = info["email"]
                msg.attach(MIMEText(html_body, "html"))
                server.sendmail(SMTP_FROM, info["email"], msg.as_string())
                sent.append(info["email"])
            except Exception as e:
                app.logger.error(f"Failed to send to {info['email']}: {e}")
                failed.append(info["email"])
        server.quit()
    except smtplib.SMTPException as e:
        return jsonify({"success": False, "message": f"SMTP error: {str(e)}"}), 500

    fz.log_activity(request, current_user(), "email_low_attendance",
                    "attendance", f"sent={len(sent)} failed={len(failed)}")
    msg = f"Email sent to {len(sent)} student(s)."
    if failed:
        msg += f" {len(failed)} failed — check server logs."
    return jsonify({"success": True, "sent": len(sent), "failed": len(failed), "message": msg})


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


@app.route("/api/alert-count")
@login_required
def api_alert_count():
    count = query_one("SELECT COUNT(*) c FROM injection_alerts")["c"]
    return jsonify({"count": count})


# ============================================================================
# Student Dashboard
# ============================================================================
@app.route("/student-dashboard")
@role_required("student")
def student_dashboard():
    from datetime import date as _date
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    )
    sid = student["id"] if student else None

    attendance_pct = 0.0
    if sid:
        att = query_all(
            "SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) p, COUNT(*) t "
            "FROM attendance WHERE student_id = ?", (sid,)
        )
        if att and att[0]["t"]:
            attendance_pct = round((att[0]["p"] / att[0]["t"]) * 100, 1)

    pending_assignments = 0
    if sid:
        pending_assignments = query_one(
            "SELECT COUNT(*) c FROM assignments a "
            "WHERE (a.due_date IS NULL OR a.due_date >= date('now')) "
            "AND a.id NOT IN (SELECT assignment_id FROM homework_submissions WHERE student_id = ?)",
            (sid,)
        )["c"]

    cgpa = 0.0
    if sid:
        cgpa_row = query_one(
            "SELECT ROUND(AVG(grade_points), 2) cgpa FROM results WHERE student_id = ?", (sid,)
        )
        cgpa = cgpa_row["cgpa"] if cgpa_row and cgpa_row["cgpa"] else 0.0

    fee_status_label = "N/A"
    if sid:
        fee_rows = query_all("SELECT status FROM fee_status WHERE student_id = ?", (sid,))
        if fee_rows:
            statuses = [r["status"] for r in fee_rows]
            if all(s == "paid" for s in statuses):
                fee_status_label = "Paid"
            elif any(s == "pending" for s in statuses):
                fee_status_label = "Pending"
            else:
                fee_status_label = "Partial"

    upcoming_exams = query_all(
        "SELECT subject, exam_type, exam_date, exam_time, venue FROM exam_schedule "
        "WHERE exam_date >= date('now') "
        "AND (department IS NULL OR department = '' OR department = ?) "
        "AND (year IS NULL OR year = 0 OR year = ?) "
        "ORDER BY exam_date ASC LIMIT 5",
        (user_db["branch"] or "", user_db["year"] or 0)
    )

    recent_notices = query_all(
        "SELECT title, body, is_pinned, created_at FROM notices "
        "WHERE target_role IN ('all','student') ORDER BY is_pinned DESC, id DESC LIMIT 5"
    )

    tasks = []
    if pending_assignments > 0:
        tasks.append({"icon": "📝", "label": f"{pending_assignments} assignment{'s' if pending_assignments > 1 else ''} pending", "detail": "Check assignments section", "url": "/assignments"})
    if fee_status_label == "Pending":
        tasks.append({"icon": "💰", "label": "Fee payment pending", "detail": "Dues outstanding", "url": "/fees"})
    if attendance_pct > 0 and attendance_pct < 75:
        tasks.append({"icon": "⚠️", "label": "Attendance below 75%", "detail": f"Current: {attendance_pct}%", "url": "/attendance"})
    open_griev = query_one(
        "SELECT COUNT(*) c FROM grievances WHERE student_id = ? AND status IN ('open','in_review')", (u["id"],)
    )
    if open_griev and open_griev["c"] > 0:
        tasks.append({"icon": "📨", "label": "Grievance awaiting response", "detail": f"{open_griev['c']} open", "url": "/grievances"})

    recent_activity = query_all(
        "SELECT action, module, timestamp FROM activity_logs WHERE user_id = ? ORDER BY id DESC LIMIT 8",
        (u["id"],)
    )

    fz.log_activity(request, u, "view", "student_dashboard")
    return render_template("student_dashboard.html",
                           student=student,
                           attendance_pct=attendance_pct,
                           pending_assignments=pending_assignments,
                           cgpa=cgpa,
                           fee_status_label=fee_status_label,
                           upcoming_exams=upcoming_exams,
                           recent_notices=recent_notices,
                           tasks=tasks,
                           recent_activity=recent_activity,
                           now_date=_date.today().strftime("%B %d, %Y"))


# ============================================================================
# Notifications
# ============================================================================
def _get_student_notifications(u):
    execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            icon TEXT DEFAULT '🔔',
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return query_all(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        (u["id"],)
    )


@app.route("/notifications")
@role_required("student")
def notifications():
    u = current_user()
    notifs = _get_student_notifications(u)
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (u["id"],))
    return render_template("notifications.html", notifications=notifs)


@app.route("/notifications/mark-read", methods=["POST"])
@role_required("student")
def notifications_mark_read():
    u = current_user()
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (u["id"],))
    return redirect(url_for("notifications"))


@app.route("/api/notifications")
@login_required
def api_notifications():
    from datetime import datetime as _dt
    u = current_user()
    if u["role"] != "student":
        return jsonify({"notifications": []})
    notifs = _get_student_notifications(u)
    result = []
    for n in notifs:
        try:
            created = _dt.fromisoformat(n["created_at"])
            diff = _dt.now() - created
            if diff.days > 0:
                time_ago = f"{diff.days}d ago"
            elif diff.seconds > 3600:
                time_ago = f"{diff.seconds // 3600}h ago"
            else:
                time_ago = f"{diff.seconds // 60}m ago"
        except Exception:
            time_ago = ""
        result.append({
            "id": n["id"], "title": n["title"], "body": n["body"],
            "icon": n["icon"], "is_read": bool(n["is_read"]),
            "time_ago": time_ago, "created_at": n["created_at"]
        })
    return jsonify({"notifications": result})


@app.route("/api/notifications/mark-read", methods=["POST"])
@login_required
def api_notifications_mark_read():
    u = current_user()
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (u["id"],))
    return jsonify({"ok": True})


# ============================================================================
# Global Search
# ============================================================================
@app.route("/api/search")
@login_required
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q or len(q) < 2:
        return jsonify({"results": []})
    u = current_user()
    like = f"%{q}%"
    results = []
    notices = query_all(
        "SELECT title FROM notices WHERE title LIKE ? AND target_role IN ('all', ?) LIMIT 3",
        (like, u["role"])
    )
    for n in notices:
        results.append({"title": n["title"], "category": "Notice", "icon": "📢", "url": "/notices"})
    exams = query_all(
        "SELECT subject, exam_date FROM exam_schedule WHERE subject LIKE ? ORDER BY exam_date ASC LIMIT 3",
        (like,)
    )
    for e in exams:
        results.append({"title": e["subject"], "category": f"Exam · {e['exam_date']}", "icon": "🗓️", "url": "/exams"})
    assignments = query_all(
        "SELECT title, subject FROM assignments WHERE title LIKE ? OR subject LIKE ? LIMIT 3",
        (like, like)
    )
    for a in assignments:
        results.append({"title": a["title"], "category": f"Assignment · {a['subject']}", "icon": "📝", "url": "/assignments"})
    if u["role"] == "student":
        results_rows = query_all(
            "SELECT r.subject, r.semester FROM results r "
            "JOIN students s ON s.id = r.student_id "
            "JOIN users us ON us.email = s.email "
            "WHERE us.id = ? AND r.subject LIKE ? LIMIT 3",
            (u["id"], like)
        )
        for r in results_rows:
            results.append({"title": r["subject"], "category": f"Result · Sem {r['semester']}", "icon": "📊", "url": "/results"})
    return jsonify({"results": results[:8]})


# ============================================================================
# Downloads
# ============================================================================
@app.route("/downloads")
@role_required("student")
def downloads():
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    )
    files = []
    if student:
        try:
            files = query_all(
                "SELECT * FROM uploaded_files WHERE student_id = ? ORDER BY uploaded_at DESC",
                (student["id"],)
            )
        except Exception:
            files = []
    fz.log_activity(request, u, "view", "downloads")
    return render_template("downloads.html", student=student, files=files)


@app.route("/downloads/result")
@role_required("student")
def download_result():
    import io, csv
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    )
    if not student:
        flash("Student record not found.", "error")
        return redirect(url_for("downloads"))
    results = query_all(
        "SELECT * FROM results WHERE student_id = ? ORDER BY semester, subject",
        (student["id"],)
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Semester", "Subject", "Internal", "External", "Total", "Max", "Grade", "Grade Points", "Status"])
    for r in results:
        writer.writerow([r["semester"], r["subject"], r["internal_marks"], r["external_marks"],
                         r["total_marks"], r["max_marks"], r["grade"], r["grade_points"], r["status"]])
    fz.log_activity(request, u, "download_result", "downloads")
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=result_{student['roll_number']}.csv"}
    )


@app.route("/downloads/attendance")
@role_required("student")
def download_attendance():
    import io, csv
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    )
    if not student:
        flash("Student record not found.", "error")
        return redirect(url_for("downloads"))
    att_data = query_all("""
        SELECT subject,
               COUNT(*) total,
               SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) present,
               ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
        FROM attendance WHERE student_id = ?
        GROUP BY subject ORDER BY subject
    """, (student["id"],))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Subject", "Classes Attended", "Total Classes", "Percentage"])
    for r in att_data:
        writer.writerow([r["subject"], r["present"], r["total"], r["pct"]])
    fz.log_activity(request, u, "download_attendance", "downloads")
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=attendance_{student['roll_number']}.csv"}
    )


@app.route("/downloads/fee-receipt")
@role_required("student")
def download_fee_receipt():
    import io, csv
    u = current_user()
    user_db = query_one("SELECT * FROM users WHERE id = ?", (u["id"],))
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    )
    if not student:
        flash("Student record not found.", "error")
        return redirect(url_for("downloads"))
    fee_rows = query_all(
        "SELECT * FROM fee_status WHERE student_id = ? ORDER BY semester, fee_type",
        (student["id"],)
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Semester", "Fee Type", "Amount", "Paid", "Status", "Due Date", "Paid Date"])
    for r in fee_rows:
        writer.writerow([r["semester"], r["fee_type"], r["amount"], r["paid_amount"],
                         r["status"], r["due_date"] or "", r["paid_date"] or ""])
    fz.log_activity(request, u, "download_fee_receipt", "downloads")
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=fee_receipt_{student['roll_number']}.csv"}
    )


# ============================================================================
# Profile extra columns (safe migration)
# ============================================================================
def _ensure_profile_columns():
    for col, typ in [("address","TEXT"), ("dob","TEXT"), ("guardian_name","TEXT"), ("emergency_contact","TEXT")]:
        try:
            execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except Exception:
            pass

_ensure_profile_columns()


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