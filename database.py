"""
Centralized database access layer — v2 (IDon Portal Enhanced).
"""
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

from config import Config


def get_connection():
    conn = sqlite3.connect(Config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# ----------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK(role IN ('admin','faculty','student')),
    full_name       TEXT NOT NULL,
    otp_code TEXT,
    otp_expiry DATETIME,
    contact_no      TEXT,
    branch          TEXT,
    university      TEXT,
    year            INTEGER,
    profile_complete INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_number  TEXT UNIQUE NOT NULL,
    full_name    TEXT NOT NULL,
    email        TEXT NOT NULL,
    department   TEXT NOT NULL,
    year         INTEGER NOT NULL,
    section      TEXT NOT NULL DEFAULT 'A',
    cgpa         REAL,
    phone        TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Attendance tracking
CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject     TEXT NOT NULL,
    date        TEXT NOT NULL,
    status      TEXT NOT NULL CHECK(status IN ('present','absent')),
    marked_by   INTEGER REFERENCES users(id),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, subject, date)
);

-- Assignments uploaded by faculty
CREATE TABLE IF NOT EXISTS assignments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    description   TEXT,
    subject       TEXT NOT NULL,
    department    TEXT,
    year          INTEGER,
    due_date      TEXT,
    stored_name   TEXT NOT NULL,
    original_name TEXT NOT NULL,
    uploaded_by   INTEGER REFERENCES users(id),
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Homework submitted by students
CREATE TABLE IF NOT EXISTS homework_submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id   INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    stored_name     TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    submitted_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(assignment_id, student_id)
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   TEXT,
    action     TEXT NOT NULL,
    module     TEXT NOT NULL,
    details    TEXT,
    ip_address TEXT,
    user_agent TEXT,
    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   TEXT,
    role       TEXT,
    entry_hash TEXT,
    status     TEXT NOT NULL CHECK(status IN ('success','failed','locked')),
    ip_address TEXT,
    user_agent TEXT,
    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_access_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   TEXT,
    filename   TEXT,
    action     TEXT NOT NULL,
    ip_address TEXT,
    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    uploaded_by   INTEGER REFERENCES users(id),
    student_id    INTEGER REFERENCES students(id),
    file_size     INTEGER,
    uploaded_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS injection_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    username    TEXT,
    input_field TEXT,
    payload     TEXT,
    ip_address  TEXT,
    alert_time  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Notices & Announcements
CREATE TABLE IF NOT EXISTS notices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    target_role TEXT NOT NULL DEFAULT 'all',
    posted_by   INTEGER REFERENCES users(id),
    is_pinned   INTEGER NOT NULL DEFAULT 0,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Exam Schedule
CREATE TABLE IF NOT EXISTS exam_schedule (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT NOT NULL,
    exam_type     TEXT NOT NULL DEFAULT 'midterm',
    exam_date     TEXT NOT NULL,
    exam_time     TEXT NOT NULL,
    venue         TEXT NOT NULL,
    department    TEXT,
    year          INTEGER,
    duration_mins INTEGER DEFAULT 180,
    created_by    INTEGER REFERENCES users(id),
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Results / Marksheet
CREATE TABLE IF NOT EXISTS results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject        TEXT NOT NULL,
    semester       INTEGER NOT NULL,
    internal_marks REAL DEFAULT 0,
    external_marks REAL DEFAULT 0,
    total_marks    REAL DEFAULT 0,
    max_marks      REAL DEFAULT 100,
    grade          TEXT,
    grade_points   REAL,
    status         TEXT NOT NULL DEFAULT 'pass',
    posted_by      INTEGER REFERENCES users(id),
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, subject, semester)
);

-- Fee Status
CREATE TABLE IF NOT EXISTS fee_status (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    semester    INTEGER NOT NULL,
    fee_type    TEXT NOT NULL DEFAULT 'tuition',
    amount      REAL NOT NULL,
    paid_amount REAL NOT NULL DEFAULT 0,
    due_date    TEXT,
    paid_date   TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    remarks     TEXT,
    updated_by  INTEGER REFERENCES users(id),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, semester, fee_type)
);

-- Grievances
CREATE TABLE IF NOT EXISTS grievances (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject      TEXT NOT NULL,
    description  TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'academic',
    status       TEXT NOT NULL DEFAULT 'open',
    response     TEXT,
    responded_by INTEGER REFERENCES users(id),
    responded_at DATETIME,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Courses
CREATE TABLE IF NOT EXISTS courses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    code           TEXT NOT NULL UNIQUE,
    subject        TEXT NOT NULL,
    semester       INTEGER NOT NULL,
    department     TEXT NOT NULL,
    section        TEXT NOT NULL DEFAULT 'A',
    academic_year  TEXT NOT NULL DEFAULT '2024-25',
    credits        INTEGER NOT NULL DEFAULT 4,
    created_by     INTEGER REFERENCES users(id),
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Faculty assigned to courses
CREATE TABLE IF NOT EXISTS course_faculty (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    faculty_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(course_id, faculty_id)
);

-- Students enrolled in courses
CREATE TABLE IF NOT EXISTS enrollments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(course_id, student_id)
);
"""


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def query_all(sql, params=()):
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def query_one(sql, params=()):
    conn = get_connection()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def execute(sql, params=()):
    conn = get_connection()
    cur = conn.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def seed():
    if query_one("SELECT id FROM users WHERE username = ?", ("admin",)):
        return

    # branch is used for faculty to scope them to a single department, so
    # course assignment (see seed_igdtuw_data.py) doesn't hand one faculty
    # member every course in the university.
    accounts = [
        ("admin",   "admin@igdtuw.edu",   "Admin@123",   "admin",   "System Administrator", None),
        ("faculty", "faculty@igdtuw.edu", "Faculty@123", "faculty", "Dr. Priya Sharma",      "CSE"),
        ("student", "student@igdtuw.edu", "Student@123", "student", "Rohan Verma",           None),
    ]
    for username, email, pw, role, name, branch in accounts:
        execute(
            "INSERT INTO users (username, email, password_hash, role, full_name, branch, profile_complete) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, email, generate_password_hash(pw), role, name, branch, 1),
        )

    sample_students = [
        ("CU22BCS001", "Aarav Singh",  "aarav@cu.edu",  "CSE", 3, 8.4, "9876500001"),
        ("CU22BCS002", "Diya Patel",   "diya@cu.edu",   "CSE", 3, 9.1, "9876500002"),
        ("CU21BME045", "Kabir Khan",   "kabir@cu.edu",  "ME",  4, 7.6, "9876500003"),
        ("CU23BEC112", "Ananya Reddy", "ananya@cu.edu", "ECE", 2, 8.9, "9876500004"),
    ]
    for roll, name, email, dept, year, cgpa, phone in sample_students:
        execute(
            "INSERT INTO students (roll_number, full_name, email, department, year, cgpa, phone, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (roll, name, email, dept, year, cgpa, phone, 1),
        )

    # Seed sample attendance
    import random
    students = query_all("SELECT id FROM students")
    subjects = ["Mathematics", "DSA", "OS", "DBMS", "Networks"]
    for s in students:
        for subj in subjects:
            for i in range(1, 21):
                date = f"2025-06-{i:02d}"
                status = "present" if random.random() > 0.3 else "absent"
                try:
                    execute(
                        "INSERT INTO attendance (student_id, subject, date, status, marked_by) VALUES (?, ?, ?, ?, ?)",
                        (s["id"], subj, date, status, 1)
                    )
                except Exception:
                    pass


def seed_extras():
    """Seed sample data for new tables if not already present."""
    if query_one("SELECT id FROM notices LIMIT 1"):
        return

    # Sample notices
    notices_data = [
        ("Welcome to the New Semester", "Classes for Semester 5 begin on July 1. Please check your timetable and report to your respective departments.", "general", "all", 1, 1),
        ("Mid-Semester Exam Schedule Released", "The mid-semester examination schedule has been published. Please check the Exam Schedule section.", "exam", "student", 1, 1),
        ("Faculty Meeting – July 5", "All faculty members are required to attend the departmental meeting on July 5 at 10:00 AM in Conference Room A.", "meeting", "faculty", 1, 0),
        ("Fee Payment Deadline", "Last date for semester fee payment is July 15. Students with pending dues should clear them to avoid a late fine.", "fee", "student", 1, 0),
        ("Library Hours Extended", "The central library will remain open until 10 PM on all weekdays during the exam period.", "general", "all", 1, 0),
    ]
    for title, body, cat, target, posted_by, pinned in notices_data:
        execute(
            "INSERT INTO notices (title, body, category, target_role, posted_by, is_pinned) VALUES (?,?,?,?,?,?)",
            (title, body, cat, target, posted_by, pinned)
        )

    # Sample exam schedule
    exams = [
        ("Mathematics",  "midterm", "2025-07-10", "09:00 AM", "Hall A", "CSE", 3, 180),
        ("DSA",          "midterm", "2025-07-11", "09:00 AM", "Hall B", "CSE", 3, 180),
        ("OS",           "midterm", "2025-07-12", "09:00 AM", "Hall A", "CSE", 3, 180),
        ("DBMS",         "midterm", "2025-07-13", "02:00 PM", "Hall C", "CSE", 3, 180),
        ("Networks",     "midterm", "2025-07-14", "09:00 AM", "Hall B", "CSE", 3, 180),
        ("Mathematics",  "midterm", "2025-07-10", "09:00 AM", "Hall D", "ME",  4, 180),
        ("Thermodynamics","midterm","2025-07-11", "02:00 PM", "Hall D", "ME",  4, 180),
    ]
    for subj, etype, date, time_, venue, dept, year, dur in exams:
        execute(
            "INSERT INTO exam_schedule (subject, exam_type, exam_date, exam_time, venue, department, year, duration_mins, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (subj, etype, date, time_, venue, dept, year, dur, 1)
        )

    # Sample results
    students = query_all("SELECT id FROM students")
    subjects = ["Mathematics", "DSA", "OS", "DBMS", "Networks"]
    import random
    grade_map = [
        (93,"A+",10),(85,"A",9),(77,"B+",8),
        (69,"B",7),(61,"C+",6),(53,"C",5),(45,"D",4),(0,"F",0)
    ]
    for s in students:
        for sem in [3, 4]:
            for subj in subjects:
                internal = round(random.uniform(15, 30), 1)
                external = round(random.uniform(35, 70), 1)
                total = internal + external
                grade, gp = "F", 0
                for threshold, g, points in grade_map:
                    if total >= threshold:
                        grade, gp = g, points
                        break
                status = "pass" if total >= 45 else "fail"
                try:
                    execute(
                        "INSERT OR IGNORE INTO results (student_id, subject, semester, internal_marks, "
                        "external_marks, total_marks, max_marks, grade, grade_points, status, posted_by) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (s["id"], subj, sem, internal, external, total, 100, grade, gp, status, 1)
                    )
                except Exception:
                    pass

    # Sample fee status
    for s in students:
        for sem in [3, 4]:
            for fee_type, amount in [("tuition", 45000), ("hostel", 15000), ("library", 500)]:
                paid = amount if sem == 3 else 0
                status = "paid" if paid >= amount else "pending"
                try:
                    execute(
                        "INSERT OR IGNORE INTO fee_status (student_id, semester, fee_type, amount, paid_amount, "
                        "due_date, status, updated_by) VALUES (?,?,?,?,?,?,?,?)",
                        (s["id"], sem, fee_type, amount, paid, "2025-07-15", status, 1)
                    )
                except Exception:
                    pass

def seed_courses():
    """Seed sample courses and enroll students into them."""
    if query_one("SELECT id FROM courses LIMIT 1"):
        return

    # Get faculty and admin users
    faculty = query_one("SELECT id FROM users WHERE role='faculty' LIMIT 1")
    admin   = query_one("SELECT id FROM users WHERE role='admin' LIMIT 1")
    if not faculty or not admin:
        return
    fid = faculty["id"]
    aid = admin["id"]

    # Create courses
    courses = [
        ("Mathematics III",   "CSE-M3-S5-A",  "Mathematics",  5, "CSE", "A", "2024-25", 4),
        ("DBMS",              "CSE-DB-S5-A",  "DBMS",         5, "CSE", "A", "2024-25", 4),
        ("Operating Systems", "CSE-OS-S5-A",  "OS",           5, "CSE", "A", "2024-25", 4),
        ("DSA",               "CSE-DSA-S3-A", "DSA",          3, "CSE", "A", "2024-25", 4),
        ("Networks",          "CSE-NET-S5-A", "Networks",     5, "CSE", "A", "2024-25", 4),
        ("Mathematics II",    "IT-M2-S3-A",   "Mathematics",  3, "IT",  "A", "2024-25", 4),
        ("DBMS",              "IT-DB-S3-A",   "DBMS",         3, "IT",  "A", "2024-25", 4),
    ]
    for name, code, subj, sem, dept, sec, yr, cred in courses:
        execute(
            "INSERT OR IGNORE INTO courses (name, code, subject, semester, department, section, academic_year, credits, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, code, subj, sem, dept, sec, yr, cred, aid)
        )

    # Assign faculty to all courses
    all_courses = query_all("SELECT id FROM courses")
    for c in all_courses:
        execute(
            "INSERT OR IGNORE INTO course_faculty (course_id, faculty_id) VALUES (?,?)",
            (c["id"], fid)
        )

    # Enroll all students into courses matching their dept+semester
    # (students table has department and year; map year → semester range)
    students = query_all("SELECT id, department, year FROM students")
    for s in students:
        dept = s["department"]
        year = s["year"] or 1
        # A year-3 student is in semesters 5 and 6; year-2 → sem 3,4; year-1 → sem 1,2
        sem_low  = (year - 1) * 2 + 1
        sem_high = sem_low + 1
        relevant = query_all(
            "SELECT id FROM courses WHERE department=? AND semester IN (?,?)",
            (dept, sem_low, sem_high)
        )
        for c in relevant:
            execute(
                "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?,?)",
                (c["id"], s["id"])
            )

    print("Courses seeded and students enrolled.")


# ============================================================================
# Migration helpers — run once to add columns/tables to existing DBs
# ============================================================================
def migrate_db():
    """Apply schema migrations to an existing database safely."""
    conn = get_connection()
    cur = conn.cursor()

    # 1. Add user_id FK to students (security fix for name-based lookups)
    try:
        cur.execute("ALTER TABLE students ADD COLUMN user_id INTEGER REFERENCES users(id)")
    except Exception:
        pass  # already exists

    # 2. Add credits to results (needed for proper weighted CGPA)
    try:
        cur.execute("ALTER TABLE results ADD COLUMN credits INTEGER DEFAULT 4")
    except Exception:
        pass

    # 3. Add is_late to homework_submissions
    try:
        cur.execute("ALTER TABLE homework_submissions ADD COLUMN is_late INTEGER DEFAULT 0")
    except Exception:
        pass

    # 3b. Add section to students (enables section-aware bulk enrollment —
    # previously "Bulk Enroll" matched dept+year only and swept in every
    # section, not just the one the course was created for)
    try:
        cur.execute("ALTER TABLE students ADD COLUMN section TEXT NOT NULL DEFAULT 'A'")
    except Exception:
        pass

    # 4. SGPA drafts table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sgpa_drafts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            semester    INTEGER NOT NULL,
            subject     TEXT NOT NULL,
            grade       TEXT NOT NULL,
            credits     INTEGER NOT NULL DEFAULT 4,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, semester, subject)
        )
    """)

    # 5. Timetable / class schedule
    cur.execute("""
        CREATE TABLE IF NOT EXISTS timetable (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id   INTEGER REFERENCES courses(id) ON DELETE CASCADE,
            department  TEXT NOT NULL,
            semester    INTEGER NOT NULL,
            section     TEXT NOT NULL DEFAULT 'A',
            day_of_week TEXT NOT NULL,
            start_time  TEXT NOT NULL,
            end_time    TEXT NOT NULL,
            room        TEXT,
            faculty_id  INTEGER REFERENCES users(id),
            subject     TEXT NOT NULL,
            academic_year TEXT NOT NULL DEFAULT '2024-25',
            created_by  INTEGER REFERENCES users(id),
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 6. Leave applications
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leave_applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            faculty_id      INTEGER REFERENCES users(id),
            subject         TEXT,
            leave_type      TEXT NOT NULL DEFAULT 'medical',
            from_date       TEXT NOT NULL,
            to_date         TEXT NOT NULL,
            reason          TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            faculty_remark  TEXT,
            reviewed_by     INTEGER REFERENCES users(id),
            reviewed_at     DATETIME,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def backfill_user_id():
    """Link existing student records to users via email."""
    students = query_all("SELECT id, email FROM students WHERE user_id IS NULL")
    for s in students:
        user = query_one("SELECT id FROM users WHERE email = ?", (s["email"],))
        if user:
            execute("UPDATE students SET user_id = ? WHERE id = ?", (user["id"], s["id"]))


def seed_timetable():
    """Seed sample timetable data if empty."""
    if query_one("SELECT id FROM timetable LIMIT 1"):
        return
    faculty = query_one("SELECT id FROM users WHERE role='faculty' LIMIT 1")
    admin   = query_one("SELECT id FROM users WHERE role='admin' LIMIT 1")
    fid = faculty["id"] if faculty else 1
    aid = admin["id"] if admin else 1

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    slots = [
        ("09:00", "10:00"), ("10:00", "11:00"), ("11:15", "12:15"),
        ("02:00", "03:00"), ("03:00", "04:00"),
    ]
    subjects = [
        ("Mathematics", 5, "CSE"), ("DSA", 5, "CSE"), ("OS", 5, "CSE"),
        ("DBMS", 5, "CSE"), ("Networks", 5, "CSE"),
    ]
    import random
    random.seed(42)
    for day in days:
        used_slots = random.sample(slots, 3)
        for (start, end), (subj, sem, dept) in zip(used_slots, random.sample(subjects, 3)):
            try:
                execute(
                    "INSERT OR IGNORE INTO timetable "
                    "(department, semester, section, day_of_week, start_time, end_time, "
                    "room, faculty_id, subject, academic_year, created_by) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (dept, sem, "A", day, start, end, f"Room {random.randint(101,310)}",
                     fid, subj, "2024-25", aid)
                )
            except Exception:
                pass


# ============================================================================
# v3 Enhanced migrations
# ============================================================================
def migrate_v3(conn):
    """Run once — adds columns/tables introduced in v3 Enhanced."""
    cur = conn.cursor()

    # 2FA columns on users
    for col_sql in [
        "ALTER TABLE users ADD COLUMN totp_secret TEXT",
        "ALTER TABLE users ADD COLUMN totp_enabled INTEGER DEFAULT 0",
        # Registration approval workflow
        "ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'",
        # Password expiry tracking
        "ALTER TABLE users ADD COLUMN last_password_change DATETIME DEFAULT CURRENT_TIMESTAMP",
    ]:
        try:
            cur.execute(col_sql)
        except Exception:
            pass  # column already exists

    # Ensure existing users get 'active' status (not NULL)
    cur.execute("UPDATE users SET status='active' WHERE status IS NULL")

    conn.commit()


def migrate_v4(conn):
    """v4 additions: in-app notification center."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message    TEXT NOT NULL,
            link       TEXT,
            is_read    INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read)")
    conn.commit()


def create_notification(user_id, message, link=None):
    """Insert a single in-app notification for one user."""
    return execute(
        "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
        (user_id, message, link),
    )


def notify_users(user_ids, message, link=None):
    """Insert the same notification for multiple users (e.g. all students)."""
    for uid in set(user_ids):
        create_notification(uid, message, link)


if __name__ == "__main__":
    init_db()
    migrate_db()
    seed()
    seed_extras()
    seed_courses()
    backfill_user_id()
    seed_timetable()
    migrate_v3(get_connection())
    print("Database initialized and seeded at", Config.DB_PATH)