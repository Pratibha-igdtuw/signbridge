"""
faculty_analytics.py — Performance Analytics Module (Faculty Enhancement #3)
==============================================================================
Per-course analytics dashboard for Faculty: attendance, marks, assignment
submission and pass-rate summaries, scoped strictly to courses the
requesting faculty member is assigned to. Admins may view any course.

Attendance/results in this codebase are keyed by (student_id, subject,
semester) rather than course_id directly (see attendance / results tables
in database.py), so analytics join on course.subject + course.semester,
scoped to the set of students actually enrolled in the course.

Security:
  - A faculty member requesting a course they are NOT assigned to gets a
    logged HTTP 403 (unauthorized_analytics_access), never partial data.
  - All views are logged to the Digital Audit Trail.
"""
from flask import Blueprint, abort, render_template, request

from auth import role_required, current_user
from database import query_all, query_one
import forensics as fz
from course_common import (get_faculty_courses, is_faculty_of_course,
                            get_all_courses, get_course, get_enrolled_students)

faculty_analytics_bp = Blueprint("faculty_analytics", __name__, url_prefix="/analytics/faculty")


def _log(action: str, details: str = "", status: str = "success"):
    u = current_user()
    role = u["role"] if u else "anonymous"
    fz.log_activity(request, u, action, "performance_analytics",
                     f"{details} role={role} status={status}".strip())


def _compute_course_analytics(course: dict) -> dict:
    """Return the full analytics payload for a single course."""
    students = get_enrolled_students(course["id"])
    student_ids = [s["id"] for s in students]
    total_students = len(students)

    result = {
        "total_students": total_students,
        "avg_attendance": None,
        "avg_marks": None,
        "above_90_count": 0,
        "below_75_attendance_count": 0,
        "at_risk_count": 0,
        "assignment_submission_pct": None,
        "pass_percentage": None,
        "attendance_buckets": {"90-100": 0, "75-89": 0, "50-74": 0, "<50": 0},
        "marks_buckets": {"90-100": 0, "75-89": 0, "50-74": 0, "<50": 0},
        "pass_count": 0,
        "fail_count": 0,
    }
    if not student_ids:
        return result

    placeholders = ",".join("?" for _ in student_ids)

    # ── Attendance per student for this course's subject ──
    att_rows = query_all(f"""
        SELECT student_id,
               ROUND(100.0 * SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) / COUNT(*), 1) pct
        FROM attendance
        WHERE subject = ? AND student_id IN ({placeholders})
        GROUP BY student_id
    """, [course["subject"], *student_ids])

    at_risk_ids = set()
    if att_rows:
        pcts = [r["pct"] for r in att_rows]
        result["avg_attendance"] = round(sum(pcts) / len(pcts), 1)
        result["below_75_attendance_count"] = sum(1 for p in pcts if p < 75)
        for p in pcts:
            if p >= 90:
                result["attendance_buckets"]["90-100"] += 1
            elif p >= 75:
                result["attendance_buckets"]["75-89"] += 1
            elif p >= 50:
                result["attendance_buckets"]["50-74"] += 1
            else:
                result["attendance_buckets"]["<50"] += 1
        for r in att_rows:
            if r["pct"] < 75:
                at_risk_ids.add(r["student_id"])

    # ── Marks / results for this course's subject + semester ──
    res_rows = query_all(f"""
        SELECT student_id, total_marks, max_marks, status
        FROM results
        WHERE subject = ? AND semester = ? AND student_id IN ({placeholders})
    """, [course["subject"], course["semester"], *student_ids])

    if res_rows:
        pct_scores = [
            (r["total_marks"] / r["max_marks"] * 100) if r["max_marks"] else 0
            for r in res_rows
        ]
        result["avg_marks"] = round(sum(pct_scores) / len(pct_scores), 1)
        result["above_90_count"] = sum(1 for p in pct_scores if p >= 90)
        result["pass_count"] = sum(1 for r in res_rows if r["status"] == "pass")
        result["fail_count"] = sum(1 for r in res_rows if r["status"] != "pass")
        total_graded = result["pass_count"] + result["fail_count"]
        result["pass_percentage"] = (
            round(100.0 * result["pass_count"] / total_graded, 1) if total_graded else None
        )
        for p in pct_scores:
            if p >= 90:
                result["marks_buckets"]["90-100"] += 1
            elif p >= 75:
                result["marks_buckets"]["75-89"] += 1
            elif p >= 50:
                result["marks_buckets"]["50-74"] += 1
            else:
                result["marks_buckets"]["<50"] += 1
        for r in res_rows:
            if r["status"] != "pass":
                at_risk_ids.add(r["student_id"])

    # ── Assignment submission rate for this subject ──
    assignments = query_all("SELECT id FROM assignments WHERE subject = ?", (course["subject"],))
    if assignments and student_ids:
        assignment_ids = [a["id"] for a in assignments]
        a_placeholders = ",".join("?" for _ in assignment_ids)
        expected = len(assignment_ids) * total_students
        submitted = query_one(f"""
            SELECT COUNT(*) c FROM homework_submissions
            WHERE assignment_id IN ({a_placeholders}) AND student_id IN ({placeholders})
        """, [*assignment_ids, *student_ids])["c"]
        result["assignment_submission_pct"] = (
            round(100.0 * submitted / expected, 1) if expected else None
        )

    result["at_risk_count"] = len(at_risk_ids)
    return result


@faculty_analytics_bp.route("/")
@role_required("admin", "faculty")
def index():
    u = current_user()
    department_filter = request.args.get("department", "").strip()
    semester_filter = request.args.get("semester", type=int)
    course_id = request.args.get("course_id", type=int)

    if u["role"] == "faculty":
        courses = get_faculty_courses(u["id"])
    else:
        courses = get_all_courses()

    if department_filter:
        courses = [c for c in courses if c["department"] == department_filter]
    if semester_filter:
        courses = [c for c in courses if c["semester"] == semester_filter]

    departments = sorted({c["department"] for c in (get_faculty_courses(u["id"]) if u["role"] == "faculty" else get_all_courses())})
    semesters = sorted({c["semester"] for c in (get_faculty_courses(u["id"]) if u["role"] == "faculty" else get_all_courses())})

    selected_course = None
    analytics = None

    if course_id:
        selected_course = get_course(course_id)
        if not selected_course:
            abort(404)
        if u["role"] == "faculty" and not is_faculty_of_course(u["id"], course_id):
            _log("unauthorized_analytics_access", f"course_id={course_id}", status="denied")
            abort(403)
        analytics = _compute_course_analytics(selected_course)
        _log("viewed_analytics",
             f"course_id={course_id} course={selected_course['code']} dept={selected_course['department']}")
    elif courses:
        # Default to the first visible course so the dashboard is never empty.
        selected_course = courses[0]
        analytics = _compute_course_analytics(selected_course)
        _log("viewed_analytics",
             f"course_id={selected_course['id']} course={selected_course['code']} "
             f"dept={selected_course['department']}")
    else:
        _log("viewed_analytics", "no_courses_available")

    return render_template("analytics/faculty.html",
                           courses=courses, departments=departments, semesters=semesters,
                           department_filter=department_filter, semester_filter=semester_filter,
                           selected_course=selected_course, analytics=analytics)
