"""
One-off provisioning script:
  1. Creates 3 real admin accounts (Namita Singh, Pratibha Mittal, Pavani Bansal)
     with freshly generated random passwords (printed once — save them immediately).
  2. Deactivates (is_active = 0) the shipped demo accounts (admin / faculty / student)
     so their well-known default passwords (Admin@123 etc.) can no longer be used to
     log in. They are NOT deleted, to avoid breaking any created_by foreign keys.

Edit ADMINS below with the real usernames/emails you want before running.

Usage:
    python provision_admins.py            # dry run - shows what would happen
    python provision_admins.py --confirm  # actually creates accounts + deactivates demo accounts
"""
import sys
import secrets
import string
from database import get_connection, query_one
from werkzeug.security import generate_password_hash

# ---- EDIT THESE before running --------------------------------------------
ADMINS = [
    # (username,        email,                          full_name)
    ("namita.singh",   "namita.singh@igdtuw.ac.in",   "Namita Singh"),
    ("pratibha.mittal","pratibha.mittal@igdtuw.ac.in","Pratibha Mittal"),
    ("pavani.bansal",  "pavani.bansal@igdtuw.ac.in",  "Pavani Bansal"),
]
DEMO_USERNAMES = ["admin", "faculty", "student"]
# -----------------------------------------------------------------------------


def generate_password(length=14):
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "!@#$%&*" for c in pw)):
            return pw


def main():
    confirm = "--confirm" in sys.argv

    print("Will create these admin accounts:")
    generated = []
    for username, email, full_name in ADMINS:
        exists = query_one("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
        pw = generate_password()
        generated.append((username, email, full_name, pw))
        status = "SKIP (already exists)" if exists else "create"
        print(f"  [{status}] {username:20} {email:35} {full_name}")

    print(f"\nWill deactivate these demo accounts (is_active=0): {', '.join(DEMO_USERNAMES)}")

    if not confirm:
        print("\nDry run only — nothing was changed. Re-run with --confirm to apply.")
        return

    conn = get_connection()
    cur = conn.cursor()

    created_creds = []
    for username, email, full_name, pw in generated:
        existing = cur.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()
        if existing:
            continue
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role, full_name, profile_complete, is_active) "
            "VALUES (?, ?, ?, 'admin', ?, 1, 1)",
            (username, email, generate_password_hash(pw), full_name),
        )
        created_creds.append((username, email, full_name, pw))

    placeholders = ",".join("?" for _ in DEMO_USERNAMES)
    cur.execute(f"UPDATE users SET is_active = 0 WHERE username IN ({placeholders})", DEMO_USERNAMES)
    deactivated = cur.rowcount

    conn.commit()
    conn.close()

    print(f"\nCreated {len(created_creds)} admin account(s). Deactivated {deactivated} demo account(s).\n")
    if created_creds:
        print("SAVE THESE CREDENTIALS NOW — they will not be shown again:")
        print("-" * 70)
        for username, email, full_name, pw in created_creds:
            print(f"  {full_name:20} | username: {username:20} | password: {pw}")
        print("-" * 70)
        print("Recommend each person changes their password after first login.")


if __name__ == "__main__":
    main()