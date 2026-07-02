"""
course_common.py — Shared helpers for Faculty Module Enhancements
===================================================================
Small, dependency-free helpers reused by:
  - course_materials.py   (Course Materials)
  - class_announcements.py (Class Announcements)
  - faculty_analytics.py  (Performance Analytics)

Kept separate (instead of duplicated in each blueprint) so the three
feature modules stay small, and so course/enrollment lookups are
implemented exactly once.
"""
from database import query_all, query_one


def get_student_record(user_id: int):
    """Resolve the `students` row linked to a logged-in student user.

    Mirrors the lookup already used by syllabus.py / app.py so behaviour
    stays consistent across the whole app.
    """
    user_db = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user_db:
        return None
    student = query_one("SELECT * FROM students WHERE user_id = ?", (user_id,))
    if not student:
        student = query_one("SELECT * FROM students WHERE email = ?", (user_db["email"],))
    if not student:
        student = query_one("SELECT * FROM students WHERE full_name = ?", (user_db["full_name"],))
    return student


def get_faculty_courses(faculty_id: int):
    """All courses assigned to a faculty member."""
    return query_all("""
        SELECT c.* FROM courses c
        JOIN course_faculty cf ON cf.course_id = c.id
        WHERE cf.faculty_id = ?
        ORDER BY c.department, c.semester, c.name
    """, (faculty_id,))


def is_faculty_of_course(faculty_id: int, course_id: int) -> bool:
    """True only if this faculty member is explicitly assigned to the course."""
    return query_one(
        "SELECT id FROM course_faculty WHERE course_id=? AND faculty_id=?",
        (course_id, faculty_id)
    ) is not None


def get_student_courses(student_id: int):
    """All courses a student is enrolled in."""
    return query_all("""
        SELECT c.* FROM courses c
        JOIN enrollments e ON e.course_id = c.id
        WHERE e.student_id = ?
        ORDER BY c.department, c.semester, c.name
    """, (student_id,))


def is_student_enrolled(student_id: int, course_id: int) -> bool:
    return query_one(
        "SELECT id FROM enrollments WHERE course_id=? AND student_id=?",
        (course_id, student_id)
    ) is not None


def get_all_courses():
    """Admin-only convenience: every course in the system."""
    return query_all("SELECT * FROM courses ORDER BY department, semester, name")


def get_course(course_id: int):
    return query_one("SELECT * FROM courses WHERE id = ?", (course_id,))


def get_enrolled_students(course_id: int):
    """Students enrolled in a given course."""
    return query_all("""
        SELECT s.* FROM students s
        JOIN enrollments e ON e.student_id = s.id
        WHERE e.course_id = ?
        ORDER BY s.roll_number
    """, (course_id,))
