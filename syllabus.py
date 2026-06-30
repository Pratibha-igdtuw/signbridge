"""
syllabus.py — Secure Scheme & Syllabus Module
==============================================
Handles:
  - Student: Browse semesters → subjects → view/download PDFs
  - Admin:   Upload, replace, archive, restore, delete PDFs
  - Security: Auth, RBAC, directory traversal protection,
              SHA-256 integrity checks, audit logging
"""

import hashlib
import io
import os
import re
import uuid

from datetime import datetime
from flask import (Blueprint, abort, flash, jsonify, redirect,
                   render_template, request, send_file, session, url_for)
from werkzeug.utils import secure_filename

from auth import login_required, role_required, current_user
from database import execute, query_all, query_one
import forensics as fz

# ── Blueprint ───────────────────────────────────────────────────────────────
syllabus_bp = Blueprint("syllabus", __name__, url_prefix="/syllabus")

# ── Constants ───────────────────────────────────────────────────────────────
SYLLABUS_ROOT   = os.path.join(os.path.dirname(__file__), "static", "pdfs", "syllabus")
MAX_UPLOAD_MB   = 10
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
PDF_MAGIC       = b"%PDF"          # first 4 bytes of every valid PDF

SEMESTER_LABELS = {
    1: "Semester I",   2: "Semester II",  3: "Semester III",
    4: "Semester IV",  5: "Semester V",   6: "Semester VI",
    7: "Semester VII", 8: "Semester VIII",
}

# ── Programme / Department catalog ────────────────────────────────────────────
PROGRAMMES = ["B.Tech", "M.Tech", "MCA", "BCA", "B.Sc", "M.Sc"]

DEPARTMENTS_BY_PROGRAMME = {
    "B.Tech": ["CSE", "IT", "AI & DS", "ECE", "ME", "CE", "EE"],
    "M.Tech": ["CSE", "IT", "AI & DS", "ECE", "ME", "CE"],
    "MCA":    ["CS"],
    "BCA":    ["CS"],
    "B.Sc":   ["CS", "Physics", "Chemistry", "Mathematics"],
    "M.Sc":   ["CS", "Physics", "Chemistry", "Mathematics"],
}

ALL_DEPARTMENTS = sorted({d for depts in DEPARTMENTS_BY_PROGRAMME.values() for d in depts})


def _safe_programme(raw) -> str | None:
    return raw if raw in PROGRAMMES else None


def _safe_department(raw) -> str | None:
    return raw if raw in ALL_DEPARTMENTS else None


def _student_record(user_id: int):
    """Look up the students table row linked to this user, including programme/department/semester."""
    user_db = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user_db:
        return None
    student = query_one(
        "SELECT * FROM students WHERE email = ? OR full_name = ?",
        (user_db["email"], user_db["full_name"])
    )
    return student

# ── DB bootstrap ─────────────────────────────────────────────────────────────
def init_syllabus_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    execute("""
        CREATE TABLE IF NOT EXISTS syllabus_subjects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            programme    TEXT    NOT NULL DEFAULT 'B.Tech',
            department   TEXT    NOT NULL DEFAULT 'CSE',
            academic_year TEXT   NOT NULL DEFAULT '',
            semester     INTEGER NOT NULL,
            subject_name TEXT    NOT NULL,
            course_code  TEXT    NOT NULL,
            credits      INTEGER DEFAULT 4,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(programme, department, academic_year, semester, course_code)
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS syllabus_documents (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id   INTEGER NOT NULL REFERENCES syllabus_subjects(id),
            doc_type     TEXT    NOT NULL CHECK(doc_type IN ('scheme','syllabus')),
            stored_name  TEXT    NOT NULL,
            original_name TEXT   NOT NULL,
            sha256       TEXT    NOT NULL,
            version      INTEGER NOT NULL DEFAULT 1,
            status       TEXT    NOT NULL DEFAULT 'active'
                         CHECK(status IN ('active','archived')),
            uploaded_by  INTEGER,
            uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            academic_year TEXT
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS syllabus_views (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            doc_type   TEXT    NOT NULL,
            viewed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Safe migration: add programme/department/academic_year to subjects
    #    table if this DB was created before this feature existed ──
    for col, typ, default in [
        ("programme", "TEXT", "'B.Tech'"),
        ("department", "TEXT", "'CSE'"),
        ("academic_year", "TEXT", "''"),
    ]:
        try:
            execute(f"ALTER TABLE syllabus_subjects ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}")
        except Exception:
            pass  # column already exists

    # ── Safe migration: add programme + current_semester to students table
    #    so we can scope what each student is allowed to see ──
    for col, typ in [
        ("programme", "TEXT"),
        ("current_semester", "INTEGER"),
    ]:
        try:
            execute(f"ALTER TABLE students ADD COLUMN {col} {typ}")
        except Exception:
            pass  # column already exists

    # Backfill: if current_semester is null, derive from `year` (1→sem 1-2, etc.)
    # Conservative default: year*2-1 (the earlier semester of that year)
    try:
        execute("""
            UPDATE students
            SET current_semester = (year * 2) - 1
            WHERE current_semester IS NULL AND year IS NOT NULL
        """)
    except Exception:
        pass

    # Backfill: if programme is null, default to B.Tech (most common case)
    try:
        execute("""
            UPDATE students
            SET programme = 'B.Tech'
            WHERE programme IS NULL OR programme = ''
        """)
    except Exception:
        pass

# ── Helpers ──────────────────────────────────────────────────────────────────
def _sem_dir(programme: str, department: str, semester: int) -> str:
    """Folder layout: static/pdfs/syllabus/<programme>/<department>/semester<N>/"""
    safe_prog = re.sub(r'[^A-Za-z0-9.]+', '_', programme or "unknown")
    safe_dept = re.sub(r'[^A-Za-z0-9.&]+', '_', department or "unknown")
    return os.path.join(SYLLABUS_ROOT, safe_prog, safe_dept, f"semester{semester}")

def _safe_semester(raw) -> int | None:
    try:
        s = int(raw)
        return s if 1 <= s <= 8 else None
    except (TypeError, ValueError):
        return None

def _safe_doc_type(raw: str) -> str | None:
    return raw if raw in ("scheme", "syllabus") else None

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _verify_integrity(path: str, expected_hash: str) -> bool:
    try:
        return _sha256(path) == expected_hash
    except OSError:
        return False

def _is_valid_pdf(stream) -> bool:
    """Check magic bytes then rewind."""
    header = stream.read(4)
    stream.seek(0)
    return header == PDF_MAGIC

def _log(action: str, details: str = "", status: str = "success"):
    """
    Write a structured entry to the existing Digital Audit Trail.
    `details` should already contain programme/department/semester/subject
    context formatted as key=value pairs, e.g.
        "programme=B.Tech dept=CSE sem=6 subject=CS601 status=denied"
    """
    u = current_user()
    full_details = f"{details} status={status}".strip()
    fz.log_activity(request, u, action, "syllabus", full_details)

def _record_view(user_id: int, subject_id: int, doc_type: str):
    execute(
        "INSERT INTO syllabus_views (user_id, subject_id, doc_type) VALUES (?,?,?)",
        (user_id, subject_id, doc_type)
    )

def _recently_viewed(user_id: int, limit: int = 5):
    return query_all("""
        SELECT sv.subject_id, ss.subject_name, ss.course_code, ss.semester,
               sv.doc_type, MAX(sv.viewed_at) last_seen
        FROM syllabus_views sv
        JOIN syllabus_subjects ss ON ss.id = sv.subject_id
        WHERE sv.user_id = ?
        GROUP BY sv.subject_id, sv.doc_type
        ORDER BY last_seen DESC
        LIMIT ?
    """, (user_id, limit))

# ── Student routes ────────────────────────────────────────────────────────────

@syllabus_bp.route("/")
@login_required
def index():
    """Semester grid — scoped to the student's own programme/department."""
    u = current_user()

    if u["role"] == "student":
        student = _student_record(u["id"])
        if not student or not student["programme"] or not student["department"]:
            # Profile incomplete — cannot safely scope content
            flash("Your academic profile is incomplete. Contact admin to set your "
                  "Programme, Department and Semester.", "error")
            _log("view_index_blocked", "Incomplete student profile", status="denied")
            return render_template("syllabus/index.html",
                                   semester_labels=SEMESTER_LABELS,
                                   counts={},
                                   recently=[],
                                   student_locked=True,
                                   student=None)

        counts = {row["semester"]: row["c"] for row in query_all(
            "SELECT semester, COUNT(*) c FROM syllabus_subjects "
            "WHERE programme=? AND department=? GROUP BY semester",
            (student["programme"], student["department"])
        )}
        recently = _recently_viewed(u["id"])
        _log("view_index",
             f"programme={student['programme']} dept={student['department']}")

        return render_template("syllabus/index.html",
                               semester_labels=SEMESTER_LABELS,
                               counts=counts,
                               recently=recently,
                               student_locked=False,
                               student=student)

    # Admin / faculty — see the full catalog across all programmes/departments
    counts = {row["semester"]: row["c"] for row in query_all(
        "SELECT semester, COUNT(*) c FROM syllabus_subjects GROUP BY semester"
    )}
    recently = _recently_viewed(u["id"])
    _log("view_index", "Full catalog (staff)")

    return render_template("syllabus/index.html",
                           semester_labels=SEMESTER_LABELS,
                           counts=counts,
                           recently=recently,
                           student_locked=False,
                           student=None)


@syllabus_bp.route("/semester/<int:semester>")
@login_required
def semester_subjects(semester):
    """List subjects for a semester — scoped to the student's programme/department."""
    if _safe_semester(semester) is None:
        abort(404)

    u = current_user()
    q = request.args.get("q", "").strip()

    student = None
    if u["role"] == "student":
        student = _student_record(u["id"])
        if not student or not student["programme"] or not student["department"]:
            flash("Your academic profile is incomplete. Contact admin.", "error")
            _log("view_semester_blocked", f"sem={semester}", status="denied")
            return redirect(url_for("syllabus.index"))

        # Hard block: students may only browse their own current semester.
        if student["current_semester"] and int(student["current_semester"]) != semester:
            _log("cross_semester_attempt",
                 f"programme={student['programme']} dept={student['department']} "
                 f"requested_sem={semester} own_sem={student['current_semester']}",
                 status="denied")
            abort(403)

        scope_sql = "AND ss.programme=? AND ss.department=?"
        scope_params = [student["programme"], student["department"]]
    else:
        scope_sql = ""
        scope_params = []

    base_select = """
        SELECT ss.*,
               (SELECT COUNT(*) FROM syllabus_documents sd
                WHERE sd.subject_id=ss.id AND sd.status='active' AND sd.doc_type='scheme') has_scheme,
               (SELECT COUNT(*) FROM syllabus_documents sd
                WHERE sd.subject_id=ss.id AND sd.status='active' AND sd.doc_type='syllabus') has_syllabus
        FROM syllabus_subjects ss
        WHERE ss.semester=?
    """
    params = [semester] + scope_params

    if q:
        base_select += " AND (LOWER(ss.subject_name) LIKE ? OR LOWER(ss.course_code) LIKE ?) "
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]

    base_select += scope_sql + " ORDER BY ss.course_code"
    subjects = query_all(base_select, params)

    _log("view_semester",
         f"sem={semester}" + (f" programme={student['programme']} dept={student['department']}"
                              if student else " (staff)"))

    return render_template("syllabus/semester.html",
                           semester=semester,
                           label=SEMESTER_LABELS[semester],
                           subjects=subjects,
                           q=q,
                           student=student)


def _authorize_subject_access(u: dict, subject: dict) -> bool:
    """
    Returns True if the current user is allowed to access this subject's documents.
    Students: must match their own programme + department + current_semester exactly.
    Admin/Faculty: unrestricted (view/download only — uploads are admin-only elsewhere).
    Any failure is logged as a denied access attempt by the caller.
    """
    if u["role"] != "student":
        return True

    student = _student_record(u["id"])
    if not student or not student["programme"] or not student["department"]:
        return False

    if student["programme"] != subject["programme"]:
        return False
    if student["department"] != subject["department"]:
        return False
    if student["current_semester"] and int(student["current_semester"]) != subject["semester"]:
        return False

    return True


@syllabus_bp.route("/view/<int:subject_id>/<doc_type>")
@login_required
def view_pdf(subject_id, doc_type):
    """Embedded PDF viewer page."""
    u = current_user()
    doc_type = _safe_doc_type(doc_type)
    if not doc_type:
        abort(404)

    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (subject_id,))
    if not subject:
        abort(404)

    if not _authorize_subject_access(u, subject):
        _log("unauthorized_cross_dept_attempt",
             f"subject={subject['course_code']} programme={subject['programme']} "
             f"dept={subject['department']} sem={subject['semester']} type={doc_type}",
             status="denied")
        abort(403)

    doc = query_one("""
        SELECT * FROM syllabus_documents
        WHERE subject_id=? AND doc_type=? AND status='active'
        ORDER BY version DESC LIMIT 1
    """, (subject_id, doc_type))

    if not doc:
        return render_template("syllabus/empty.html",
                               subject=subject,
                               doc_type=doc_type,
                               label=SEMESTER_LABELS.get(subject["semester"], ""))

    # Integrity check before showing viewer
    path = os.path.join(_sem_dir(subject["programme"], subject["department"], subject["semester"]), doc["stored_name"])
    if not os.path.exists(path) or not _verify_integrity(path, doc["sha256"]):
        _log("integrity_fail", f"subject={subject['course_code']} type={doc_type}", status="failed")
        return render_template("syllabus/integrity_fail.html", subject=subject)

    _record_view(u["id"], subject_id, doc_type)
    action = "viewed_scheme" if doc_type == "scheme" else "viewed_syllabus"
    _log(action,
         f"subject={subject['course_code']} programme={subject['programme']} "
         f"dept={subject['department']} sem={subject['semester']}")

    return render_template("syllabus/viewer.html",
                           subject=subject,
                           doc=doc,
                           doc_type=doc_type,
                           label=SEMESTER_LABELS.get(subject["semester"], ""),
                           pdf_url=url_for("syllabus.serve_pdf",
                                           subject_id=subject_id,
                                           doc_type=doc_type))


@syllabus_bp.route("/serve/<int:subject_id>/<doc_type>")
@login_required
def serve_pdf(subject_id, doc_type):
    """Serve PDF inline (for iframe). Never auto-downloads."""
    u = current_user()
    doc_type = _safe_doc_type(doc_type)
    if not doc_type:
        abort(404)

    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (subject_id,))
    if not subject:
        abort(404)

    if not _authorize_subject_access(u, subject):
        _log("unauthorized_cross_dept_attempt",
             f"serve subject={subject['course_code']} programme={subject['programme']} "
             f"dept={subject['department']} sem={subject['semester']} type={doc_type}",
             status="denied")
        abort(403)

    doc = query_one("""
        SELECT * FROM syllabus_documents
        WHERE subject_id=? AND doc_type=? AND status='active'
        ORDER BY version DESC LIMIT 1
    """, (subject_id, doc_type))

    if not doc:
        abort(404)

    path = os.path.join(_sem_dir(subject["programme"], subject["department"], subject["semester"]), doc["stored_name"])

    # Security: verify path stays inside SYLLABUS_ROOT
    real_path    = os.path.realpath(path)
    real_root    = os.path.realpath(SYLLABUS_ROOT)
    if not real_path.startswith(real_root + os.sep):
        _log("traversal_blocked", f"Attempted path: {path}", status="denied")
        abort(403)

    if not os.path.exists(real_path):
        abort(404)

    if not _verify_integrity(real_path, doc["sha256"]):
        _log("integrity_fail", f"Serve blocked: {doc['stored_name']}", status="failed")
        abort(403)

    return send_file(
        real_path,
        mimetype="application/pdf",
        as_attachment=False,          # inline — no automatic download
        download_name=doc["original_name"],
        conditional=True,
    )


@syllabus_bp.route("/download/<int:subject_id>/<doc_type>")
@login_required
def download_pdf(subject_id, doc_type):
    """Force-download PDF. Only triggered by explicit button click."""
    u = current_user()
    doc_type = _safe_doc_type(doc_type)
    if not doc_type:
        abort(404)

    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (subject_id,))
    if not subject:
        abort(404)

    if not _authorize_subject_access(u, subject):
        _log("unauthorized_cross_dept_attempt",
             f"download subject={subject['course_code']} programme={subject['programme']} "
             f"dept={subject['department']} sem={subject['semester']} type={doc_type}",
             status="denied")
        abort(403)

    doc = query_one("""
        SELECT * FROM syllabus_documents
        WHERE subject_id=? AND doc_type=? AND status='active'
        ORDER BY version DESC LIMIT 1
    """, (subject_id, doc_type))

    if not doc:
        abort(404)

    path = os.path.join(_sem_dir(subject["programme"], subject["department"], subject["semester"]), doc["stored_name"])
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(SYLLABUS_ROOT)

    if not real_path.startswith(real_root + os.sep):
        _log("traversal_blocked", f"Download traversal: {path}", status="denied")
        abort(403)

    if not os.path.exists(real_path):
        abort(404)

    if not _verify_integrity(real_path, doc["sha256"]):
        _log("integrity_fail_download", f"Download blocked: {doc['stored_name']}", status="failed")
        abort(403)

    _log("downloaded_pdf",
         f"subject={subject['course_code']} programme={subject['programme']} "
         f"dept={subject['department']} sem={subject['semester']} type={doc_type}")
    return send_file(
        real_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=doc["original_name"],
    )


@syllabus_bp.route("/search")
@login_required
def search():
    """Search subjects. Students are restricted to their own programme/department."""
    u = current_user()
    q = request.args.get("q", "").strip()
    sem = _safe_semester(request.args.get("sem"))
    results = []

    student = None
    if u["role"] == "student":
        student = _student_record(u["id"])
        if not student or not student["programme"] or not student["department"]:
            flash("Your academic profile is incomplete. Contact admin.", "error")
            return render_template("syllabus/search.html",
                                   results=[], q=q, sem=sem,
                                   semester_labels=SEMESTER_LABELS)

    if q or sem:
        base = """
            SELECT ss.*,
                   (SELECT COUNT(*) FROM syllabus_documents sd
                    WHERE sd.subject_id=ss.id AND sd.status='active') doc_count
            FROM syllabus_subjects ss
            WHERE 1=1
        """
        params = []
        if q:
            base += " AND (LOWER(ss.subject_name) LIKE ? OR LOWER(ss.course_code) LIKE ?)"
            params += [f"%{q.lower()}%", f"%{q.lower()}%"]
        if sem:
            base += " AND ss.semester=?"
            params.append(sem)
        if student:
            base += " AND ss.programme=? AND ss.department=?"
            params += [student["programme"], student["department"]]
        base += " ORDER BY ss.semester, ss.course_code"
        results = query_all(base, params)

    _log("search", f"q='{q}' sem={sem}" + (f" programme={student['programme']} dept={student['department']}" if student else ""))

    return render_template("syllabus/search.html",
                           results=results,
                           q=q,
                           sem=sem,
                           semester_labels=SEMESTER_LABELS)


# ── Admin routes ──────────────────────────────────────────────────────────────

@syllabus_bp.route("/admin")
@role_required("admin")
def admin_index():
    """Admin management hub — filterable by programme/department/year/semester."""
    f_programme = _safe_programme(request.args.get("programme"))
    f_department = _safe_department(request.args.get("department"))
    f_year = (request.args.get("academic_year") or "").strip()
    f_semester = _safe_semester(request.args.get("semester"))

    base = """
        SELECT ss.*,
               (SELECT COUNT(*) FROM syllabus_documents sd
                WHERE sd.subject_id=ss.id AND sd.status='active') active_docs,
               (SELECT COUNT(*) FROM syllabus_documents sd
                WHERE sd.subject_id=ss.id AND sd.status='archived') archived_docs
        FROM syllabus_subjects ss
        WHERE 1=1
    """
    params = []
    if f_programme:
        base += " AND ss.programme=?"
        params.append(f_programme)
    if f_department:
        base += " AND ss.department=?"
        params.append(f_department)
    if f_year:
        base += " AND ss.academic_year=?"
        params.append(f_year)
    if f_semester:
        base += " AND ss.semester=?"
        params.append(f_semester)
    base += " ORDER BY ss.programme, ss.department, ss.semester, ss.course_code"

    subjects = query_all(base, params)

    # Distinct academic years already in use, for the filter dropdown
    years = [r["academic_year"] for r in query_all(
        "SELECT DISTINCT academic_year FROM syllabus_subjects "
        "WHERE academic_year IS NOT NULL AND academic_year != '' ORDER BY academic_year DESC"
    )]

    return render_template("syllabus/admin.html",
                           subjects=subjects,
                           semester_labels=SEMESTER_LABELS,
                           programmes=PROGRAMMES,
                           departments_by_programme=DEPARTMENTS_BY_PROGRAMME,
                           all_departments=ALL_DEPARTMENTS,
                           years=years,
                           f_programme=f_programme,
                           f_department=f_department,
                           f_year=f_year,
                           f_semester=f_semester)


@syllabus_bp.route("/admin/api/departments")
@role_required("admin")
def admin_api_departments():
    """Returns the list of departments valid for a given programme (for the dependent dropdown)."""
    programme = _safe_programme(request.args.get("programme"))
    if not programme:
        return jsonify({"departments": ALL_DEPARTMENTS})
    return jsonify({"departments": DEPARTMENTS_BY_PROGRAMME.get(programme, [])})


@syllabus_bp.route("/admin/subject/new", methods=["POST"])
@role_required("admin")
def admin_subject_new():
    """Create a new subject, scoped to Programme + Department + Academic Year."""
    u = current_user()
    programme    = _safe_programme(request.form.get("programme"))
    department   = _safe_department(request.form.get("department"))
    academic_year = (request.form.get("academic_year") or "").strip()
    semester     = _safe_semester(request.form.get("semester"))
    subject_name = (request.form.get("subject_name") or "").strip()
    course_code  = (request.form.get("course_code") or "").strip().upper()
    credits      = request.form.get("credits") or 4

    if not all([programme, department, academic_year, semester, subject_name, course_code]):
        flash("Programme, Department, Academic Year, Semester, Subject Name and "
              "Course Code are all required.", "error")
        _log("admin_add_subject_rejected", "missing required field(s)", status="rejected")
        return redirect(url_for("syllabus.admin_index"))

    # Validate academic year format: YYYY-YY (e.g. 2025-26)
    if not re.match(r'^\d{4}-\d{2}$', academic_year):
        flash("Academic Year must be in the format YYYY-YY, e.g. 2025-26.", "error")
        return redirect(url_for("syllabus.admin_index"))

    # Validate course code: letters/digits/hyphens only
    if not re.match(r'^[A-Z0-9\-]{2,20}$', course_code):
        flash("Invalid course code format.", "error")
        return redirect(url_for("syllabus.admin_index"))

    try:
        credits_int = int(credits)
        if not (1 <= credits_int <= 10):
            raise ValueError
    except (TypeError, ValueError):
        flash("Credits must be a number between 1 and 10.", "error")
        return redirect(url_for("syllabus.admin_index"))

    try:
        execute(
            "INSERT INTO syllabus_subjects "
            "(programme, department, academic_year, semester, subject_name, course_code, credits) "
            "VALUES (?,?,?,?,?,?,?)",
            (programme, department, academic_year, semester, subject_name, course_code, credits_int)
        )
        _log("admin_add_subject",
             f"programme={programme} dept={department} year={academic_year} "
             f"sem={semester} code={course_code}")
        flash(f"Subject '{subject_name}' added to {programme} {department} — "
              f"Semester {semester} ({academic_year}).", "success")
    except Exception:
        flash("A subject with that course code already exists for this "
              "Programme/Department/Year/Semester combination.", "error")

    return redirect(url_for("syllabus.admin_index"))


@syllabus_bp.route("/admin/subject/<int:subject_id>/delete", methods=["POST"])
@role_required("admin")
def admin_subject_delete(subject_id):
    """Delete subject and all its documents."""
    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (subject_id,))
    if not subject:
        abort(404)
    # Delete stored files
    docs = query_all("SELECT * FROM syllabus_documents WHERE subject_id=?", (subject_id,))
    for doc in docs:
        path = os.path.join(_sem_dir(subject["programme"], subject["department"], subject["semester"]), doc["stored_name"])
        if os.path.exists(path):
            os.remove(path)
    execute("DELETE FROM syllabus_documents WHERE subject_id=?", (subject_id,))
    execute("DELETE FROM syllabus_subjects WHERE id=?", (subject_id,))
    _log("admin_delete_subject", f"code={subject['course_code']}")
    flash(f"Subject '{subject['subject_name']}' deleted.", "success")
    return redirect(url_for("syllabus.admin_index"))


@syllabus_bp.route("/admin/upload/<int:subject_id>", methods=["POST"])
@role_required("admin")
def admin_upload(subject_id):
    """Upload or replace a PDF for a subject."""
    u = current_user()
    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (subject_id,))
    if not subject:
        abort(404)

    doc_type     = _safe_doc_type(request.form.get("doc_type"))
    academic_year = (request.form.get("academic_year") or "").strip()
    f = request.files.get("pdf_file")

    if not doc_type:
        flash("Invalid document type.", "error")
        return redirect(url_for("syllabus.admin_index"))

    if not f or f.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("syllabus.admin_index"))

    # ── Validate extension ──
    ext = os.path.splitext(f.filename)[1].lower()
    if ext != ".pdf":
        _log("invalid_upload_ext", f"ext={ext} subject={subject['course_code']}")
        flash("Only PDF files are accepted.", "error")
        return redirect(url_for("syllabus.admin_index"))

    # ── Read into memory and validate size ──
    data = f.read()
    if len(data) > MAX_UPLOAD_SIZE:
        _log("oversized_upload", f"size={len(data)} subject={subject['course_code']}")
        flash(f"File exceeds {MAX_UPLOAD_MB} MB limit.", "error")
        return redirect(url_for("syllabus.admin_index"))

    # ── Validate PDF magic bytes ──
    if data[:4] != PDF_MAGIC:
        _log("invalid_pdf_magic", f"subject={subject['course_code']}")
        flash("File does not appear to be a valid PDF.", "error")
        return redirect(url_for("syllabus.admin_index"))

    # ── Build safe stored filename ──
    safe_orig = secure_filename(f.filename)
    stored_name = f"{subject['course_code']}_SEM{subject['semester']}_{doc_type}_{uuid.uuid4().hex[:8]}.pdf"

    # ── Write to disk ──
    sem_dir = _sem_dir(subject["programme"], subject["department"], subject["semester"])
    os.makedirs(sem_dir, exist_ok=True)
    dest = os.path.join(sem_dir, stored_name)
    with open(dest, "wb") as out:
        out.write(data)

    sha = _sha256(dest)

    # ── Archive existing active version ──
    execute("""
        UPDATE syllabus_documents SET status='archived'
        WHERE subject_id=? AND doc_type=? AND status='active'
    """, (subject_id, doc_type))

    # ── Determine new version number ──
    max_ver = query_one(
        "SELECT MAX(version) v FROM syllabus_documents WHERE subject_id=? AND doc_type=?",
        (subject_id, doc_type)
    )
    new_ver = (max_ver["v"] or 0) + 1

    execute("""
        INSERT INTO syllabus_documents
            (subject_id, doc_type, stored_name, original_name, sha256, version, status, uploaded_by, academic_year)
        VALUES (?,?,?,?,?,?,'active',?,?)
    """, (subject_id, doc_type, stored_name, safe_orig, sha, new_ver, u["id"], academic_year))

    _log("admin_upload_pdf",
         f"subject={subject['course_code']} type={doc_type} ver={new_ver} sha256={sha[:16]}…")
    flash(f"PDF uploaded successfully (v{new_ver}).", "success")
    return redirect(url_for("syllabus.admin_index"))


@syllabus_bp.route("/admin/doc/<int:doc_id>/archive", methods=["POST"])
@role_required("admin")
def admin_archive(doc_id):
    """Archive (deactivate) a document."""
    doc = query_one("SELECT * FROM syllabus_documents WHERE id=?", (doc_id,))
    if not doc:
        abort(404)
    execute("UPDATE syllabus_documents SET status='archived' WHERE id=?", (doc_id,))
    _log("admin_archive_pdf", f"doc_id={doc_id} file={doc['stored_name']}")
    flash("Document archived.", "success")
    return redirect(url_for("syllabus.admin_history",
                            subject_id=doc["subject_id"]))


@syllabus_bp.route("/admin/doc/<int:doc_id>/restore", methods=["POST"])
@role_required("admin")
def admin_restore(doc_id):
    """Restore an archived document as the active version."""
    doc = query_one("SELECT * FROM syllabus_documents WHERE id=?", (doc_id,))
    if not doc:
        abort(404)
    # Archive any current active
    execute("""
        UPDATE syllabus_documents SET status='archived'
        WHERE subject_id=? AND doc_type=? AND status='active'
    """, (doc["subject_id"], doc["doc_type"]))
    execute("UPDATE syllabus_documents SET status='active' WHERE id=?", (doc_id,))
    _log("admin_restore_pdf", f"doc_id={doc_id}")
    flash("Document restored as active version.", "success")
    return redirect(url_for("syllabus.admin_history",
                            subject_id=doc["subject_id"]))


@syllabus_bp.route("/admin/doc/<int:doc_id>/delete", methods=["POST"])
@role_required("admin")
def admin_delete_doc(doc_id):
    """Permanently delete an archived document."""
    doc = query_one("SELECT * FROM syllabus_documents WHERE id=?", (doc_id,))
    if not doc:
        abort(404)
    if doc["status"] == "active":
        flash("Cannot delete the active version. Archive it first.", "error")
        return redirect(url_for("syllabus.admin_history",
                                subject_id=doc["subject_id"]))

    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (doc["subject_id"],))
    path = os.path.join(_sem_dir(subject["programme"], subject["department"], subject["semester"]), doc["stored_name"])
    if os.path.exists(path):
        os.remove(path)
    execute("DELETE FROM syllabus_documents WHERE id=?", (doc_id,))
    _log("admin_delete_pdf", f"doc_id={doc_id} file={doc['stored_name']}")
    flash("Document permanently deleted.", "success")
    return redirect(url_for("syllabus.admin_history",
                            subject_id=doc["subject_id"]))


@syllabus_bp.route("/admin/subject/<int:subject_id>/history")
@role_required("admin")
def admin_history(subject_id):
    """Version history for a subject's documents."""
    subject = query_one("SELECT * FROM syllabus_subjects WHERE id=?", (subject_id,))
    if not subject:
        abort(404)
    docs = query_all("""
        SELECT sd.*, u.full_name uploader_name
        FROM syllabus_documents sd
        LEFT JOIN users u ON u.id = sd.uploaded_by
        WHERE sd.subject_id=?
        ORDER BY sd.doc_type, sd.version DESC
    """, (subject_id,))
    return render_template("syllabus/history.html",
                           subject=subject,
                           docs=docs,
                           label=SEMESTER_LABELS.get(subject["semester"], ""))


# ── JSON search endpoint (for dynamic filtering) ─────────────────────────────
@syllabus_bp.route("/api/search")
@login_required
def api_search():
    u   = current_user()
    q   = (request.args.get("q") or "").strip()
    sem = _safe_semester(request.args.get("sem"))
    if not q and not sem:
        return jsonify({"results": []})

    student = None
    if u["role"] == "student":
        student = _student_record(u["id"])
        if not student or not student["programme"] or not student["department"]:
            return jsonify({"results": []})

    base   = "SELECT id, semester, subject_name, course_code, credits FROM syllabus_subjects WHERE 1=1"
    params = []
    if q:
        base += " AND (LOWER(subject_name) LIKE ? OR LOWER(course_code) LIKE ?)"
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]
    if sem:
        base += " AND semester=?"
        params.append(sem)
    if student:
        base += " AND programme=? AND department=?"
        params += [student["programme"], student["department"]]
    base += " ORDER BY semester, course_code LIMIT 20"
    rows = query_all(base, params)
    return jsonify({"results": [dict(r) for r in rows]})
