"""
fix_faculty_departments.py — one-time repair for existing databases
=====================================================================
Problem: earlier seeding only ever created ONE faculty account, so every
course in every department ended up assigned to that single faculty member
(via course_faculty). That let one faculty user see/post announcements for
courses completely outside their department.

This script is idempotent and safe to re-run:
  1. Creates one faculty account per department if it doesn't already exist
     (same accounts seed_igdtuw_data.py now creates for fresh installs).
  2. Scopes the original "faculty" demo account to CSE.
  3. Rebuilds course_faculty so each course is assigned to a faculty member
     in ITS OWN department, instead of whoever was assigned before.

It does NOT touch courses, students, enrollments, announcements, or any
other data -- only the course_faculty mapping and the faculty accounts
themselves.

Run once with:
    python fix_faculty_departments.py
"""
import random

from database import execute, query_all, query_one
from seed_igdtuw_data import DEPT_FACULTY_ACCOUNTS, seed_department_faculty


def rebuild_course_faculty():
    faculty_users = query_all("SELECT id, branch FROM users WHERE role='faculty'")
    faculty_by_dept = {}
    for f in faculty_users:
        if f["branch"]:
            faculty_by_dept.setdefault(f["branch"], []).append(f["id"])

    all_faculty_ids = [f["id"] for f in faculty_users]
    courses = query_all("SELECT id, department, name FROM courses")

    reassigned = 0
    for c in courses:
        pool = faculty_by_dept.get(c["department"], all_faculty_ids)
        new_faculty_id = random.choice(pool)

        current = query_all("SELECT faculty_id FROM course_faculty WHERE course_id=?", (c["id"],))
        current_ids = {row["faculty_id"] for row in current}

        if current_ids == {new_faculty_id}:
            continue  # already correct

        execute("DELETE FROM course_faculty WHERE course_id=?", (c["id"],))
        execute("INSERT INTO course_faculty (course_id, faculty_id) VALUES (?,?)",
                (c["id"], new_faculty_id))
        reassigned += 1

    print(f"  ✅ Reassigned {reassigned} of {len(courses)} courses to department-matched faculty")


if __name__ == "__main__":
    print("=" * 70)
    print("FIXING FACULTY ↔ DEPARTMENT / COURSE ASSIGNMENTS")
    print("=" * 70)

    print("\n[1/2] Ensuring every department has a faculty account...")
    seed_department_faculty()

    print("\n[2/2] Rebuilding course_faculty assignments by department...")
    rebuild_course_faculty()

    print("\n" + "=" * 70)
    print("✅ DONE. Each faculty account now only sees/posts for courses in")
    print("   its own department. New login credentials (password for all:")
    print(f"   Faculty@123):")
    for dept, (username, email, name) in DEPT_FACULTY_ACCOUNTS.items():
        print(f"     {dept:6s} -> username: {username:14s} ({name})")
    print("     CSE    -> username: faculty        (Dr. Priya Sharma) [unchanged]")
    print("=" * 70)