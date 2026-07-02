"""
course_materials.py — Course Materials Module (Faculty Enhancement #1)
========================================================================
Lets Faculty upload learning resources (Lecture Notes, Lab Manuals, PPT
Presentations, Sample Papers, Assignment Solutions, Reference Material)
for courses they are assigned to teach.

Security model (mirrors syllabus.py):
  - Only authenticated Faculty may upload/replace/delete, and only for
    courses they are assigned to (course_faculty table).
  - Extension whitelist + magic-byte / structural validation + max size.
  - Files are renamed internally (uuid) — the original filename is never
    trusted for storage.
  - SHA-256 integrity hash recorded and re-verified before every serve.
  - Students may only view/download materials for courses they are
    enrolled in.
  - Every upload / replace / delete / download is written to the
    existing Digital Audit Trail (forensics.log_activity).
"""
import hashlib
import io
import os
import uuid
import zipfile

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, send_file, url_for)
from werkzeug.utils import secure_filename

from auth import login_required, role_required, current_user
from database import execute, query_all, query_one
import forensics as fz
from course_common import (get_student_record, get_faculty_courses,
                            is_faculty_of_course, get_student_courses,
                            is_student_enrolled, get_all_courses, get_course)

materials_bp = Blueprint("materials", __name__, url_prefix="/materials")

# ── Constants ────────────────────────────────────────────────────────────
MATERIALS_ROOT = os.path.join(os.path.dirname(__file__), "uploads", "course_materials")
MAX_UPLOAD_MB = 20
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "ppt", "pptx"}

MATERIAL_TYPES = [
    "Lecture Notes", "Lab Manual", "PPT Presentation",
    "Sample Paper", "Assignment Solution", "Reference Material",
]

PDF_MAGIC = b"%PDF"
OLE_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"   # legacy .ppt (Compound File)
ZIP_MAGIC = b"PK\x03\x04"                          # .pptx is a zip archive


# ── DB bootstrap ─────────────────────────────────────────────────────────
def init_materials_db():
    execute("""
        CREATE TABLE IF NOT EXISTS course_materials (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title         TEXT    NOT NULL,
            material_type TEXT    NOT NULL DEFAULT 'Lecture Notes',
            description   TEXT,
            stored_name   TEXT    NOT NULL,
            original_name TEXT    NOT NULL,
            file_ext      TEXT    NOT NULL,
            sha256        TEXT    NOT NULL,
            file_size     INTEGER NOT NULL,
            version       INTEGER NOT NULL DEFAULT 1,
            status        TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active','deleted')),
            uploaded_by   INTEGER REFERENCES users(id),
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    os.makedirs(MATERIALS_ROOT, exist_ok=True)


# ── Helpers ──────────────────────────────────────────────────────────────
def _course_dir(course_id: int) -> str:
    return os.path.join(MATERIALS_ROOT, str(int(course_id)))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _valid_signature(ext: str, data: bytes) -> bool:
    """Best-effort structural / magic-byte validation per extension."""
    if ext == "pdf":
        return data[:4] == PDF_MAGIC
    if ext == "ppt":
        return data[:8] == OLE_MAGIC
    if ext == "pptx":
        if data[:4] != ZIP_MAGIC:
            return False
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            names = zf.namelist()
            return "[Content_Types].xml" in names and any(n.startswith("ppt/") for n in names)
        except Exception:
            return False
    return False


def _log(action: str, details: str = "", status: str = "success"):
    u = current_user()
    role = u["role"] if u else "anonymous"
    fz.log_activity(request, u, action, "course_materials",
                     f"{details} role={role} status={status}".strip())


def _authorize_view(u: dict, course_id: int) -> bool:
    """Faculty must be assigned; students must be enrolled; admin unrestricted."""
    if u["role"] == "admin":
        return True
    if u["role"] == "faculty":
        return is_faculty_of_course(u["id"], course_id)
    if u["role"] == "student":
        student = get_student_record(u["id"])
        return bool(student) and is_student_enrolled(student["id"], course_id)
    return False


# ── List / browse ────────────────────────────────────────────────────────
@materials_bp.route("/")
@login_required
def index():
    u = current_user()
    q = request.args.get("q", "").strip()
    course_filter = request.args.get("course_id", type=int)
    type_filter = request.args.get("type", "").strip()

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
            return render_template("materials/index.html", courses=[], materials=[],
                                   course_filter=None, q=q, type_filter=type_filter,
                                   material_types=MATERIAL_TYPES, student_locked=True)
        courses = get_student_courses(student["id"])

    # Validate requested course_id is actually one this user can see
    if course_filter and not any(c["id"] == course_filter for c in courses) and u["role"] != "admin":
        flash("You do not have access to that course.", "error")
        _log("unauthorized_material_access", f"course_id={course_filter}", status="denied")
        course_filter = None

    sql = """
        SELECT cm.*, c.name course_name, c.code course_code, c.subject course_subject,
               c.semester course_semester, c.department course_department,
               u.full_name uploader_name
        FROM course_materials cm
        JOIN courses c ON c.id = cm.course_id
        LEFT JOIN users u ON u.id = cm.uploaded_by
        WHERE cm.status='active'
    """
    params = []

    if u["role"] == "faculty":
        sql += " AND cm.course_id IN (SELECT course_id FROM course_faculty WHERE faculty_id=?)"
        params.append(u["id"])
    elif u["role"] == "student" and student:
        sql += " AND cm.course_id IN (SELECT course_id FROM enrollments WHERE student_id=?)"
        params.append(student["id"])
    # admin: unrestricted

    if course_filter:
        sql += " AND cm.course_id = ?"
        params.append(course_filter)
    if type_filter:
        sql += " AND cm.material_type = ?"
        params.append(type_filter)
    if q:
        sql += " AND (LOWER(cm.title) LIKE ? OR LOWER(cm.description) LIKE ?)"
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]

    sql += " ORDER BY cm.created_at DESC"
    materials = query_all(sql, params)

    _log("view_materials", f"course_id={course_filter or 'all'}")

    return render_template("materials/index.html",
                           courses=courses, materials=materials,
                           course_filter=course_filter, q=q, type_filter=type_filter,
                           material_types=MATERIAL_TYPES, student_locked=False)


# ── Faculty: upload ──────────────────────────────────────────────────────
@materials_bp.route("/upload", methods=["POST"])
@role_required("faculty")
def upload():
    u = current_user()
    course_id = request.form.get("course_id", type=int)
    title = (request.form.get("title") or "").strip()
    material_type = (request.form.get("material_type") or "").strip()
    description = (request.form.get("description") or "").strip()
    f = request.files.get("file")

    if not course_id or not is_faculty_of_course(u["id"], course_id):
        _log("unauthorized_upload_attempt", f"course_id={course_id}", status="denied")
        abort(403)

    if not title or material_type not in MATERIAL_TYPES:
        flash("Please provide a title and a valid material type.", "error")
        return redirect(url_for("materials.index", course_id=course_id))

    if not f or f.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("materials.index", course_id=course_id))

    ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        _log("invalid_file_upload", f"course_id={course_id} ext={ext}", status="rejected")
        flash("Only PDF, PPT and PPTX files are accepted.", "error")
        return redirect(url_for("materials.index", course_id=course_id))

    data = f.read()
    if len(data) > MAX_UPLOAD_SIZE:
        _log("invalid_file_upload", f"course_id={course_id} size={len(data)}", status="rejected")
        flash(f"File exceeds the {MAX_UPLOAD_MB} MB limit.", "error")
        return redirect(url_for("materials.index", course_id=course_id))

    if not _valid_signature(ext, data):
        _log("invalid_file_upload", f"course_id={course_id} ext={ext} reason=signature_mismatch",
             status="rejected")
        flash("The file content does not match its extension.", "error")
        return redirect(url_for("materials.index", course_id=course_id))

    # Rename internally; the original name is stored only for display/download.
    safe_orig = secure_filename(f.filename) or f"material.{ext}"
    stored_name = f"{uuid.uuid4().hex}.{ext}"

    course_dir = _course_dir(course_id)
    os.makedirs(course_dir, exist_ok=True)
    dest = os.path.join(course_dir, stored_name)
    with open(dest, "wb") as out:
        out.write(data)

    sha = _sha256_bytes(data)

    execute("""
        INSERT INTO course_materials
            (course_id, title, material_type, description, stored_name,
             original_name, file_ext, sha256, file_size, uploaded_by)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (course_id, title, material_type, description, stored_name,
          safe_orig, ext, sha, len(data), u["id"]))

    course = get_course(course_id)
    _log("uploaded_material",
         f"course_id={course_id} course={course['code'] if course else ''} "
         f"dept={course['department'] if course else ''} title={title} sha256={sha[:16]}…")
    flash(f"'{title}' uploaded successfully.", "success")
    return redirect(url_for("materials.index", course_id=course_id))


def _get_owned_material(u: dict, material_id: int):
    """Fetch a material row and enforce faculty-owns-course / admin rules.
    Returns (material, course) or aborts with 403/404."""
    material = query_one("SELECT * FROM course_materials WHERE id=?", (material_id,))
    if not material:
        abort(404)
    course = get_course(material["course_id"])
    if u["role"] == "admin":
        return material, course
    if u["role"] == "faculty" and is_faculty_of_course(u["id"], material["course_id"]):
        return material, course
    _log("unauthorized_material_access", f"material_id={material_id}", status="denied")
    abort(403)


# ── Faculty: replace ─────────────────────────────────────────────────────
@materials_bp.route("/<int:material_id>/replace", methods=["POST"])
@role_required("faculty", "admin")
def replace(material_id):
    u = current_user()
    material, course = _get_owned_material(u, material_id)

    f = request.files.get("file")
    if not f or f.filename == "":
        flash("No replacement file selected.", "error")
        return redirect(url_for("materials.index", course_id=material["course_id"]))

    ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        _log("invalid_file_upload", f"material_id={material_id} ext={ext}", status="rejected")
        flash("Only PDF, PPT and PPTX files are accepted.", "error")
        return redirect(url_for("materials.index", course_id=material["course_id"]))

    data = f.read()
    if len(data) > MAX_UPLOAD_SIZE:
        flash(f"File exceeds the {MAX_UPLOAD_MB} MB limit.", "error")
        return redirect(url_for("materials.index", course_id=material["course_id"]))

    if not _valid_signature(ext, data):
        _log("invalid_file_upload", f"material_id={material_id} reason=signature_mismatch",
             status="rejected")
        flash("The file content does not match its extension.", "error")
        return redirect(url_for("materials.index", course_id=material["course_id"]))

    safe_orig = secure_filename(f.filename) or f"material.{ext}"
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    course_dir = _course_dir(material["course_id"])
    os.makedirs(course_dir, exist_ok=True)
    dest = os.path.join(course_dir, stored_name)
    with open(dest, "wb") as out:
        out.write(data)
    sha = _sha256_bytes(data)

    # Remove the old physical file once the new one is safely written.
    old_path = os.path.join(course_dir, material["stored_name"])
    if os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    execute("""
        UPDATE course_materials
        SET stored_name=?, original_name=?, file_ext=?, sha256=?, file_size=?,
            version=version+1, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (stored_name, safe_orig, ext, sha, len(data), material_id))

    _log("updated_material",
         f"material_id={material_id} course_id={material['course_id']} "
         f"course={course['code'] if course else ''} dept={course['department'] if course else ''}")
    flash("Material replaced successfully.", "success")
    return redirect(url_for("materials.index", course_id=material["course_id"]))


# ── Faculty: delete ──────────────────────────────────────────────────────
@materials_bp.route("/<int:material_id>/delete", methods=["POST"])
@role_required("faculty", "admin")
def delete(material_id):
    u = current_user()
    material, course = _get_owned_material(u, material_id)

    path = os.path.join(_course_dir(material["course_id"]), material["stored_name"])
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

    execute("UPDATE course_materials SET status='deleted', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (material_id,))

    _log("deleted_material",
         f"material_id={material_id} course_id={material['course_id']} "
         f"course={course['code'] if course else ''} dept={course['department'] if course else ''} "
         f"title={material['title']}")
    flash("Material deleted.", "success")
    return redirect(url_for("materials.index", course_id=material["course_id"]))


# ── View / download ──────────────────────────────────────────────────────
@materials_bp.route("/<int:material_id>/download")
@login_required
def download(material_id):
    u = current_user()
    material = query_one("SELECT * FROM course_materials WHERE id=? AND status='active'", (material_id,))
    if not material:
        abort(404)

    if not _authorize_view(u, material["course_id"]):
        _log("unauthorized_material_access", f"material_id={material_id}", status="denied")
        abort(403)

    course_dir = _course_dir(material["course_id"])
    path = os.path.join(course_dir, material["stored_name"])
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(MATERIALS_ROOT)
    if not real_path.startswith(real_root + os.sep):
        _log("traversal_blocked", f"material_id={material_id}", status="denied")
        abort(403)
    if not os.path.exists(real_path):
        abort(404)
    if _sha256_file(real_path) != material["sha256"]:
        _log("integrity_fail", f"material_id={material_id}", status="failed")
        abort(403)

    course = get_course(material["course_id"])
    _log("downloaded_material",
         f"material_id={material_id} course_id={material['course_id']} "
         f"course={course['code'] if course else ''} dept={course['department'] if course else ''}")

    mimetypes = {"pdf": "application/pdf",
                 "ppt": "application/vnd.ms-powerpoint",
                 "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    return send_file(real_path,
                     mimetype=mimetypes.get(material["file_ext"], "application/octet-stream"),
                     as_attachment=True,
                     download_name=material["original_name"])


@materials_bp.route("/<int:material_id>/preview")
@login_required
def preview(material_id):
    """Inline preview — only offered for PDF files."""
    u = current_user()
    material = query_one("SELECT * FROM course_materials WHERE id=? AND status='active'", (material_id,))
    if not material:
        abort(404)
    if not _authorize_view(u, material["course_id"]):
        _log("unauthorized_material_access", f"material_id={material_id} action=preview", status="denied")
        abort(403)
    if material["file_ext"] != "pdf":
        return redirect(url_for("materials.download", material_id=material_id))

    course_dir = _course_dir(material["course_id"])
    path = os.path.join(course_dir, material["stored_name"])
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(MATERIALS_ROOT)
    if not real_path.startswith(real_root + os.sep) or not os.path.exists(real_path):
        abort(404)
    if _sha256_file(real_path) != material["sha256"]:
        _log("integrity_fail", f"material_id={material_id} action=preview", status="failed")
        abort(403)

    return send_file(real_path, mimetype="application/pdf", as_attachment=False,
                     download_name=material["original_name"], conditional=True)
