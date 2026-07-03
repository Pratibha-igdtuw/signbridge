"""
One-off cleanup: remove the students added by seed_igdtuw_data.py and keep only
the original 4 hand-entered records.

What this does:
  - Keeps students with roll_number in KEEP_ROLLS (the original 4).
  - Deletes every other row in `students`.
  - Because attendance / enrollments / homework_submissions / results / fee_status
    all have ON DELETE CASCADE on student_id, those related rows for the
    deleted students are removed automatically by SQLite.
  - Courses and course_faculty are NOT touched — this only cleans up students.

Safe to re-run: it's idempotent (re-running with nothing left to delete is a no-op).

Usage:
    python cleanup_seeded_students.py            # dry run - shows what would happen
    python cleanup_seeded_students.py --confirm   # actually deletes
"""
import sys
import sqlite3
from database import get_connection  # reuse the same connection helper the app uses

KEEP_ROLLS = [
    "CU22BCS001",  # Aarav Singh
    "CU22BCS002",  # Diya Patel
    "CU21BME045",  # Kabir Khan
    "CU23BEC112",  # Ananya Reddy
]

def main():
    confirm = "--confirm" in sys.argv

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join("?" for _ in KEEP_ROLLS)
    cur.execute(f"SELECT id, roll_number, full_name FROM students WHERE roll_number NOT IN ({placeholders})", KEEP_ROLLS)
    to_delete = cur.fetchall()

    cur.execute(f"SELECT id, roll_number, full_name FROM students WHERE roll_number IN ({placeholders})", KEEP_ROLLS)
    to_keep = cur.fetchall()

    print(f"Will keep {len(to_keep)} student(s):")
    for r in to_keep:
        print(f"  ✓ {r['roll_number']}  {r['full_name']}")

    print(f"\nWill delete {len(to_delete)} student(s) and their cascaded "
          f"attendance/enrollment/results/fee records.")

    if not confirm:
        print("\nDry run only — nothing was changed. Re-run with --confirm to apply.")
        conn.close()
        return

    ids = [r["id"] for r in to_delete]
    if ids:
        id_placeholders = ",".join("?" for _ in ids)
        cur.execute(f"DELETE FROM students WHERE id IN ({id_placeholders})", ids)
        conn.commit()
    print(f"\nDeleted {len(ids)} student(s). {len(to_keep)} student(s) remain.")
    conn.close()

if __name__ == "__main__":
    main()