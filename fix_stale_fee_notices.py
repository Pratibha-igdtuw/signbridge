"""
One-off cleanup: fix pre-existing fee notices that were created before
per-student notice targeting existed (target_user_id column). These notices
mention a specific student by name in the body ("Dear <Name>, ...") but were
broadcast to every student because that's all the old code could do.

For each one:
  - Try to match the student name in the body to a real user account.
  - If matched: backfill target_user_id so it's now correctly scoped.
  - If no confident match: delete it (safer than leaving it broadcasting).

Usage:
    python fix_stale_fee_notices.py            # dry run
    python fix_stale_fee_notices.py --confirm   # apply
"""
import sys
import re
from database import get_connection


def main():
    confirm = "--confirm" in sys.argv
    conn = get_connection()
    conn.row_factory = __import__("sqlite3").Row
    cur = conn.cursor()

    cur.execute(
        "SELECT id, title, body FROM notices "
        "WHERE category='fee' AND target_user_id IS NULL"
    )
    rows = cur.fetchall()

    if not rows:
        print("No stale untargeted fee notices found. Nothing to do.")
        return

    to_fix, to_delete, skipped = [], [], 0
    for r in rows:
        m = re.search(r"Dear ([A-Za-z ]+?),", r["body"])
        if not m:
            # No personal salutation at all — this is a genuine broadcast
            # notice (e.g. "Fee Payment Deadline" for everyone), not a
            # mistargeted personal one. Leave it alone entirely.
            skipped += 1
            continue
        name = m.group(1).strip()
        cur.execute(
            "SELECT u.id FROM users u JOIN students s ON s.user_id = u.id "
            "WHERE s.full_name = ?", (name,)
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "SELECT u.id FROM users u JOIN students s ON s.email = u.email "
                "WHERE s.full_name = ?", (name,)
            )
            row = cur.fetchone()
        matched_user_id = row["id"] if row else None

        if matched_user_id:
            to_fix.append((r["id"], r["title"], name, matched_user_id))
        else:
            # Named a specific student but that student has no login account
            # to target — safest to remove rather than leave it broadcasting.
            to_delete.append((r["id"], r["title"], name))

    print(f"Skipping {skipped} genuine broadcast notice(s) with no personal salutation — left untouched.\n")
    print(f"Will backfill target_user_id on {len(to_fix)} notice(s):")
    for nid, title, name, uid in to_fix:
        print(f"  [fix]    #{nid}  '{title}'  -> {name} (user id {uid})")

    print(f"\nWill delete {len(to_delete)} notice(s) with no confident student match:")
    for nid, title, name in to_delete:
        print(f"  [delete] #{nid}  '{title}'  (parsed name: {name!r})")

    if not confirm:
        print("\nDry run only — nothing was changed. Re-run with --confirm to apply.")
        conn.close()
        return

    for nid, _, _, uid in to_fix:
        cur.execute("UPDATE notices SET target_user_id=? WHERE id=?", (uid, nid))
    for nid, _, _ in to_delete:
        cur.execute("DELETE FROM notices WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    print(f"\nDone — fixed {len(to_fix)}, deleted {len(to_delete)}.")


if __name__ == "__main__":
    main()