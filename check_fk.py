import sqlite3

conn = sqlite3.connect("instance/sms.db")
cur = conn.cursor()

tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]

for table in tables:
    fks = cur.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    for fk in fks:
        if "users_old_v5" in fk[2]:
            print(f"{table} -> {fk}")

conn.close()