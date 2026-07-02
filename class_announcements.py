"""
class_announcements.py — Class Announcements Module (Faculty Enhancement #2)
==============================================================================
Faculty post announcements (Normal / Important / Urgent) scoped to courses
they are assigned to teach. Students enrolled in that course see them
automatically. Expired announcements move to an archive automatically.

Security:
  - Backend re-verifies the faculty member is assigned to the course on
    every create/edit/delete/archive — never trusts the form alone.
  - Optional PDF attachment goes through the same extension + magic-byte
    validation used by course_materials.py.
  - Every action is written to the Digital Audit Trail.
"""
import hashlib
import os
import uuid

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, send_file, url_for)
from werkzeug.utils import secure_filename

from auth import login_required, role_required, current_user
from database import execute, query_all, query_one
import forensics as fz
from course_common import (get_student_record, get_faculty_courses,
                            is_faculty_of_course, get_student_courses,
                            is_student_enrolled, get_all_courses, get_course)

announcements_bp = Blueprint("announcements", __name__, url_prefix="/announcements")

ATTACH_ROOT = os.path.join(os.path.dirname(__file__), "uploads", "announcements")
MAX_ATTACH_MB = 10
MAX_ATTACH_SIZE = MAX_ATTACH_MB * 1024 * 1024
PDF_MAGIC = b"%PDF"

PRIORITIES = ["normal", "important", "urgent"]
PRIORITY_ORDER = {"urgent": 0, "important": 1, "normal": 2}


def init_announcements_db():
    execute("""
        CREATE TABLE IF NOT EXISTS class_announcements (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title         TEXT    NOT NULL,
            description   TEXT    NOT NULL,
            priority      TEXT    NOT NULL DEFAULT 'normal' CHECK(priority IN ('normal','important','urgent')),
            attachment_stored_name   TEXT,
            attachment_original_name TEXT,
            status        TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived','deleted')),
            expires_at    TEXT,
            created_by    INTEGER REFERENCES users(id),
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    os.makedirs(ATTACH_ROOT, exist_ok=True)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _log(action: str, details: str = "", status: str = "success"):
    u = current_user()
    role = u["role"] if u else "anonymous"
    fz.log_activity(request, u, action, "class_announcements",
                     f"{details} role={role} status={status}".strip())


def _auto_archive_expired():
    """Move any past-due active announcements into the archive."""
    execute("""
        UPDATE class_announcements
        SET status='archived', updated_at=CURRENT_TIMESTAMP
        WHERE status='active' AND expires_at IS NOT NULL AND expires_at != ''
          AND date(expires_at) < date('now')
    """)


def _get_owned_announcement(u: dict, ann_id: int):
    ann = query_one("SELECT * FROM class_announcements WHERE id=?", (ann_id,))
    if not ann:
        abort(404)
    course = get_course(ann["course_id"])
    if u["role"] == "admin":
        return ann, course
    if u["role"] == "faculty" and is_faculty_of_course(u["id"], ann["course_id"]):
        return ann, course
    _log("unauthorized_announcement_attempt", f"announcement_id={ann_id}", status="denied")
    abort(403)


# ── List ─────────────────────────────────────────────────────────────────
@announcements_bp.route("/")
@login_required
def index():
    _auto_archive_expired()
    u = current_user()
    course_filter = request.args.get("course_id", type=int)
    status_filter = request.args.get("status", "active").strip()

    courses = []
    student = None

    if u["role"] == "faculty":
        courses = get_faculty_courses(u["id"])
    elif u["role"] == "admin":
        courses = get_all_courses()
    elif u["role"] == "student":
        student = get_student_record(u["id"])
        if not student:
            flash("Your academic profile is incomplete. Contact admin.", "error")
            return render_template("announcements/index.html", courses=[], announcements=[],
                                   course_filter=None, status_filter=status_filter,
                                   priorities=PRIORITIES, student_locked=True)
        courses = get_student_courses(student["id"])

    if course_filter and not any(c["id"] == course_filter for c in courses) and u["role"] != "admin":
        flash("You do not have access to that course.", "error")
        _log("unauthorized_announcement_attempt", f"course_id={course_filter}", status="denied")
        course_filter = None

    sql = """
        SELECT a.*, c.name course_name, c.code course_code, c.subject course_subject,
               c.semester course_semester, c.department course_department,
               u.full_name author_name
        FROM class_announcements a
        JOIN courses c ON c.id = a.course_id
        LEFT JOIN users u ON u.id = a.created_by
        WHERE 1=1
    """
    params = []

    if u["role"] == "student":
        sql += " AND a.status='active'"
        sql += " AND a.course_id IN (SELECT course_id FROM enrollments WHERE student_id=?)"
        params.append(student["id"])
    else:
        if u["role"] == "faculty":
            sql += " AND a.course_id IN (SELECT course_id FROM course_faculty WHERE faculty_id=?)"
            params.append(u["id"])
        # admin: unrestricted
        if status_filter in ("active", "archived"):
            sql += " AND a.status=?"
            params.append(status_filter)
        else:
            sql += " AND a.status != 'deleted'"

    if course_filter:
        sql += " AND a.course_id = ?"
        params.append(course_filter)

    sql += " ORDER BY a.created_at DESC"
    announcements = query_all(sql, params)

    # Priority-first ordering for students (urgent items float to the top)
    if u["role"] == "student":
        announcements = sorted(announcements, key=lambda a: PRIORITY_ORDER.get(a["priority"], 3))

    _log("view_announcements", f"course_id={course_filter or 'all'}")

    return render_template("announcements/index.html",
                           courses=courses, announcements=announcements,
                           course_filter=course_filter, status_filter=status_filter,
                           priorities=PRIORITIES, student_locked=False)


# ── Faculty: create ──────────────────────────────────────────────────────
@announcements_bp.route("/create", methods=["POST"])
@role_required("faculty")
def create():
    u = current_user()
    course_id = request.form.get("course_id", type=int)
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    priority = (request.form.get("priority") or "normal").strip()
    expires_at = (request.form.get("expires_at") or "").strip()
    f = request.files.get("attachment")

    if not course_id or not is_faculty_of_course(u["id"], course_id):
        _log("unauthorized_announcement_attempt", f"course_id={course_id}", status="denied")
        abort(403)

    if not title or not description:
        flash("Title and description are required.", "error")
        return redirect(url_for("announcements.index", course_id=course_id))

    if priority not in PRIORITIES:
        priority = "normal"

    attach_stored, attach_orig = None, None
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
        if ext != "pdf":
            _log("invalid_file_upload", f"course_id={course_id} ext={ext} module=announcements",
                 status="rejected")
            flash("Only PDF attachments are accepted.", "error")
            return redirect(url_for("announcements.index", course_id=course_id))
        data = f.read()
        if len(data) > MAX_ATTACH_SIZE:
            flash(f"Attachment exceeds the {MAX_ATTACH_MB} MB limit.", "error")
            return redirect(url_for("announcements.index", course_id=course_id))
        if data[:4] != PDF_MAGIC:
            _log("invalid_file_upload", f"course_id={course_id} reason=signature_mismatch",
                 status="rejected")
            flash("The attachment does not appear to be a valid PDF.", "error")
            return redirect(url_for("announcements.index", course_id=course_id))
        attach_orig = secure_filename(f.filename) or "attachment.pdf"
        attach_stored = f"{uuid.uuid4().hex}.pdf"
        course_dir = os.path.join(ATTACH_ROOT, str(course_id))
        os.makedirs(course_dir, exist_ok=True)
        with open(os.path.join(course_dir, attach_stored), "wb") as out:
            out.write(data)

    execute("""
        INSERT INTO class_announcements
            (course_id, title, description, priority, attachment_stored_name,
             attachment_original_name, expires_at, created_by)
        VALUES (?,?,?,?,?,?,?,?)
    """, (course_id, title, description, priority, attach_stored, attach_orig,
          expires_at or None, u["id"]))

    course = get_course(course_id)
    _log("created_announcement",
         f"course_id={course_id} course={course['code'] if course else ''} "
         f"dept={course['department'] if course else ''} priority={priority} title={title}")
    flash("Announcement posted.", "success")
    return redirect(url_for("announcements.index", course_id=course_id))


# ── Faculty: edit ────────────────────────────────────────────────────────
@announcements_bp.route("/<int:ann_id>/edit", methods=["POST"])
@role_required("faculty", "admin")
def edit(ann_id):
    u = current_user()
    ann, course = _get_owned_announcement(u, ann_id)

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    priority = (request.form.get("priority") or ann["priority"]).strip()
    expires_at = (request.form.get("expires_at") or "").strip()

    if not title or not description:
        flash("Title and description are required.", "error")
        return redirect(url_for("announcements.index", course_id=ann["course_id"]))
    if priority not in PRIORITIES:
        priority = ann["priority"]

    execute("""
        UPDATE class_announcements
        SET title=?, description=?, priority=?, expires_at=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (title, description, priority, expires_at or None, ann_id))

    _log("edited_announcement",
         f"announcement_id={ann_id} course_id={ann['course_id']} "
         f"course={course['code'] if course else ''} dept={course['department'] if course else ''}")
    flash("Announcement updated.", "success")
    return redirect(url_for("announcements.index", course_id=ann["course_id"]))


# ── Faculty: archive ─────────────────────────────────────────────────────
@announcements_bp.route("/<int:ann_id>/archive", methods=["POST"])
@role_required("faculty", "admin")
def archive(ann_id):
    u = current_user()
    ann, course = _get_owned_announcement(u, ann_id)
    execute("UPDATE class_announcements SET status='archived', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ann_id,))
    _log("archived_announcement",
         f"announcement_id={ann_id} course_id={ann['course_id']} "
         f"course={course['code'] if course else ''} dept={course['department'] if course else ''}")
    flash("Announcement archived.", "success")
    return redirect(url_for("announcements.index", course_id=ann["course_id"]))


# ── Faculty: delete ──────────────────────────────────────────────────────
@announcements_bp.route("/<int:ann_id>/delete", methods=["POST"])
@role_required("faculty", "admin")
def delete(ann_id):
    u = current_user()
    ann, course = _get_owned_announcement(u, ann_id)

    if ann["attachment_stored_name"]:
        path = os.path.join(ATTACH_ROOT, str(ann["course_id"]), ann["attachment_stored_name"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    execute("UPDATE class_announcements SET status='deleted', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ann_id,))
    _log("deleted_announcement",
         f"announcement_id={ann_id} course_id={ann['course_id']} "
         f"course={course['code'] if course else ''} dept={course['department'] if course else ''} "
         f"title={ann['title']}")
    flash("Announcement deleted.", "success")
    return redirect(url_for("announcements.index", course_id=ann["course_id"]))


# ── Attachment download ──────────────────────────────────────────────────
@announcements_bp.route("/<int:ann_id>/attachment")
@login_required
def attachment(ann_id):
    u = current_user()
    ann = query_one("SELECT * FROM class_announcements WHERE id=? AND status != 'deleted'", (ann_id,))
    if not ann or not ann["attachment_stored_name"]:
        abort(404)

    allowed = False
    if u["role"] == "admin":
        allowed = True
    elif u["role"] == "faculty":
        allowed = is_faculty_of_course(u["id"], ann["course_id"])
    elif u["role"] == "student":
        student = get_student_record(u["id"])
        allowed = bool(student) and is_student_enrolled(student["id"], ann["course_id"])

    if not allowed:
        _log("unauthorized_announcement_attempt", f"announcement_id={ann_id} action=attachment",
             status="denied")
        abort(403)

    course_dir = os.path.join(ATTACH_ROOT, str(ann["course_id"]))
    path = os.path.join(course_dir, ann["attachment_stored_name"])
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(ATTACH_ROOT)
    if not real_path.startswith(real_root + os.sep) or not os.path.exists(real_path):
        abort(404)

    return send_file(real_path, mimetype="application/pdf", as_attachment=True,
                     download_name=ann["attachment_original_name"])
