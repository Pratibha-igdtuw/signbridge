"""
IGDTUW Curriculum Seeding Script - Generate 20 realistic students + proper course structure
Academic Year: 2026-27

FIXED (this version):
  1. connection-churn issue that caused "database is locked" errors — each
     seeding function now uses ONE connection for its whole batch.
  2. semester-calculation bug — the previous loop only ever computed
     semester = (year-1)*2 + 1, which is always odd (1, 3, 5, 7). That meant
     semesters 2, 4, and 6 (defined in IGDTUW_DEPARTMENTS) were NEVER seeded,
     and Year 4 tried to look up semester 7, which doesn't exist in the dict
     at all, so Year 4 got nothing. This version loops over BOTH semesters
     of each of the 3 years covered by the dict (1-6), matching how the rest
     of the app computes year from semester: year = (semester + 1) // 2.
  3. enrollment count per course reduced from 60 -> 20 students.

Safe to re-run: existing course codes / student roll numbers are skipped
via UNIQUE constraint handling, and enrollments/attendance use INSERT OR IGNORE.
"""
import random
import string
from database import execute, query_all, query_one, get_connection
from datetime import datetime, timedelta

# ============================================================================
# IGDTUW Curriculum Structure (from official PDFs 2026-27)
# ============================================================================

IGDTUW_DEPARTMENTS = {
    "CSE": {
        "name": "Computer Science and Engineering",
        "prefix": "BCS",
        "semesters": {
            1: ["Programming with C", "Applied Mathematics", "Applied Physics", "Web Application Development", "Communication Skills"],
            2: ["Data Structures", "Probability and Statistics", "Environmental Sciences", "Mobile Application Development", "Soft Skills"],
            3: ["Design and Analysis of Algorithm", "Software Engineering", "Introduction to Internet of Things", "Discrete Mathematics"],
            4: ["Database Management Systems", "Computer Organization and Architecture", "Operating Systems", "Data Communication and Networks"],
            5: ["DBMS", "Operating Systems", "Networks", "Mathematics III"],
            6: ["Advanced Web Development", "Security Engineering", "Cloud Computing", "System Design"],
        }
    },
    "ECE": {
        "name": "Electronics and Communication Engineering",
        "prefix": "BEC",
        "semesters": {
            1: ["Signals and Systems", "Fundamentals of Electrical Sciences", "Applied Mathematics", "Electronics Workshop"],
            2: ["Network Analysis and Synthesis", "Environmental Sciences", "Applied Physics", "Electronic Devices & Circuit"],
            3: ["Digital System Design", "Analog Communication Systems", "Numerical Techniques", "Electronics Circuit Simulation"],
            4: ["Analog Electronics", "Electromagnetic Field Theory", "Digital Communication Systems", "Control Systems"],
            5: ["Wireless Communications", "Signal Processing", "Microelectronics", "Power Systems"],
            6: ["Advanced Communications", "VLSI Design", "Electromagnetic Compatibility", "Project Work"],
        }
    },
    "IT": {
        "name": "Information Technology",
        "prefix": "BIT",
        "semesters": {
            1: ["Programming with Python", "Applied Mathematics", "Applied Physics", "Web Application Development", "IT Workshop"],
            2: ["Object Oriented Programming", "Probability and Statistics", "Environmental Sciences", "Introduction to Data Science"],
            3: ["Data Structures and Algorithm", "Database Management Systems", "Open Source Technologies", "Discrete Mathematics"],
            4: ["Design and Analysis of Algorithms", "Operating Systems", "Software Engineering", "Statistical Modeling"],
            5: ["Cloud Computing", "Advanced Database Systems", "DevOps Fundamentals", "Data Analytics"],
            6: ["Distributed Systems", "Containerization", "Microservices Architecture", "System Design"],
        }
    },
    "AIML": {
        "name": "Artificial Intelligence and Machine Learning",
        "prefix": "BAI",
        "semesters": {
            1: ["Programming with Python", "Probability and Statistics", "Environmental Sciences", "Web Application Development"],
            2: ["Object Oriented Programming", "Applied Mathematics", "Applied Physics", "Introduction to Data Science"],
            3: ["Data Structures and Algorithm", "Database Management Systems", "Artificial Intelligence", "Machine Learning Basics"],
            4: ["Deep Learning", "Natural Language Processing", "Computer Vision", "Advanced Data Mining"],
            5: ["Reinforcement Learning", "AI Ethics", "Time Series Analysis", "Pattern Recognition"],
            6: ["Advanced Deep Learning", "Computer Vision Applications", "AI Capstone Project", "Responsible AI"],
        }
    },
    "MAE": {
        "name": "Mechanical and Automation Engineering",
        "prefix": "BMA",
        "semesters": {
            1: ["Elements of Mechanical Engineering", "Applied Mathematics", "Applied Physics", "Workshop Practice"],
            2: ["Engineering Mechanics", "Probability and Statistics", "Environmental Sciences", "CAD Modelling"],
            3: ["Production Technology I", "Engineering Materials", "Thermal Engineering I", "Robotics Lab"],
            4: ["Thermal Engineering II", "Production Technology II", "Theory of Machines", "Fluid Mechanics"],
            5: ["Heat Transfer", "Machine Design", "Manufacturing Processes", "Industrial Automation"],
            6: ["Advanced Manufacturing", "Robotics Applications", "Energy Systems", "Project Work"],
        }
    },
    "MAC": {
        "name": "Mathematics and Computing",
        "prefix": "MAC",
        "semesters": {
            1: ["Calculus I", "Programming with C", "Environmental Sciences", "Web Application Development"],
            2: ["Calculus II", "Linear Algebra", "Applied Physics", "Programming Tools for Mathematics"],
            3: ["Data Structures", "Software Engineering", "Discrete Mathematics", "IoT and Applications"],
            4: ["Design and Analysis of Algorithms", "Computer Organization", "Probability Theory", "Data Analytics"],
            5: ["Advanced Algorithms", "Cryptography", "Mathematical Modelling", "Statistical Methods"],
            6: ["Advanced Data Science", "Optimization", "Graph Theory Applications", "Capstone Project"],
        }
    }
}

# All semesters actually defined above (1 through 6 -> Years 1, 2, 3)
ALL_SEMESTERS = [1, 2, 3, 4, 5, 6]

# How many students to generate per (department, year) batch.
STUDENTS_PER_BATCH = 20

# ============================================================================
# Generate Realistic Student Data for IGDTUW
# ============================================================================

FIRST_NAMES = [
    "Aarav", "Aditya", "Arjun", "Ashok", "Amar",
    "Diya", "Divya", "Deepika", "Dharini", "Daksha",
    "Esha", "Esha", "Emaan", "Erin", "Eva",
    "Ravi", "Rahul", "Rajesh", "Rohit", "Rishabh",
    "Priya", "Pooja", "Priyanka", "Preeti", "Parminder",
    "Sakshi", "Sara", "Shreya", "Shweta", "Shilpa",
    "Karan", "Kamal", "Kabir", "Kavi", "Kushal",
    "Ananya", "Anita", "Anjali", "Akshara", "Anya",
    "Vikram", "Vikas", "Vivek", "Vihaan", "Vedant",
    "Neha", "Nisha", "Nandini", "Naina", "Nikita",
    "Harsh", "Harpreet", "Harshita", "Harpinder", "Harman",
    "Simran", "Siddhant", "Sidharth", "Siddhartha", "Sidhant",
    "Manvi", "Manas", "Manish", "Mandira", "Mahesh",
    "Tanvi", "Tarun", "Tanmay", "Tanvi", "Tapas",
    "Nivedita", "Nihar", "Nilay", "Nishant", "Nitesh",
    "Yashika", "Yash", "Yashasvi", "Yasmin", "Yogesh",
    "Zara", "Zainab", "Zeeshan", "Zubaida", "Zamir",
    "Uthara", "Ujjwal", "Uma", "Udit", "Ulka",
    "Varun", "Vedavati", "Veronica", "Vihita", "Vinay",
    "Wajid", "Wanita", "Winston", "Wasim", "Waheeda",
]

LAST_NAMES = [
    "Singh", "Verma", "Patel", "Sharma", "Kumar",
    "Gupta", "Mishra", "Rao", "Nair", "Reddy",
    "Saxena", "Joshi", "Iyer", "Desai", "Bhatt",
    "Chopra", "Malhotra", "Bhat", "Kapoor", "Arora",
    "Pandey", "Tiwari", "Srivastava", "Agarwal", "Bansal",
    "Khanna", "Sethi", "Bhatnagar", "Dhawan", "Dutta",
    "Roy", "Das", "Ghosh", "Mukherjee", "Chatterjee",
    "Menon", "Krishnan", "Pillai", "Subramaniam", "Sundaram",
    "Kale", "Kulkarni", "Naik", "Sardesai", "Bendre",
    "Hegde", "Shenoy", "Rath", "Nayak", "Patnaik",
]

def generate_roll_number(dept, year, index):
    """Generate realistic IGDTUW roll number: CU24BCS001"""
    year_map = {1: "24", 2: "23", 3: "22", 4: "21"}
    prefix = IGDTUW_DEPARTMENTS[dept]["prefix"]
    year_code = year_map.get(year, "24")
    return f"CU{year_code}{prefix}{index:03d}"

def generate_email(full_name, dept, index):
    """Generate realistic email"""
    name_part = full_name.lower().replace(" ", ".")
    return f"{name_part}.{index}@igdtuw.ac.in"

def generate_phone():
    """Generate Indian phone number"""
    return f"98{random.randint(10000000, 99999999)}"

def generate_students_for_course(dept, year, count=STUDENTS_PER_BATCH):
    """Generate students for a department/year batch (default: STUDENTS_PER_BATCH),
    round-robin distributed across sections A/B/C."""
    sections = ["A", "B", "C"]
    students = []
    for i in range(1, count + 1):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        full_name = f"{first} {last}"

        roll_number = generate_roll_number(dept, year, i)
        email = generate_email(full_name, dept, i)
        phone = generate_phone()
        cgpa = round(random.uniform(6.5, 9.5), 2)
        section = sections[(i - 1) % len(sections)]

        students.append({
            "roll_number": roll_number,
            "full_name": full_name,
            "email": email,
            "department": dept,
            "year": year,
            "cgpa": cgpa,
            "phone": phone,
            "section": section,
        })
    return students

DEPT_FACULTY_ACCOUNTS = {
    # dept_code: (username, email, full_name)
    # "CSE" is intentionally omitted -- the default "faculty" account
    # (Dr. Priya Sharma) created in database.py:seed() already covers CSE.
    "ECE":   ("faculty_ece",  "faculty.ece@igdtuw.ac.in",  "Dr. Neha Kapoor"),
    "IT":    ("faculty_it",   "faculty.it@igdtuw.ac.in",   "Dr. Ritu Malhotra"),
    "AIML": ("faculty_aiml", "faculty.aiml@igdtuw.ac.in", "Dr. Ananya Rao"),
    "MAE":   ("faculty_mae",  "faculty.mae@igdtuw.ac.in",  "Dr. Sunita Verma"),
    "MAC":   ("faculty_mac",  "faculty.mac@igdtuw.ac.in",  "Dr. Kavita Iyer"),
}
DEFAULT_FACULTY_PASSWORD = "Faculty@123"


def seed_department_faculty():
    """Ensure every department has its own faculty account.

    Without this, all courses across every department end up assigned to
    whichever single faculty account exists (see seed_departments_and_courses
    below), which lets one faculty member post announcements / see records
    for courses far outside their department.
    """
    from werkzeug.security import generate_password_hash

    # Scope the original demo account (created in database.py:seed()) to CSE
    # if it isn't already tagged with a department.
    execute("UPDATE users SET branch='CSE' WHERE username='faculty' AND role='faculty' "
            "AND (branch IS NULL OR branch = '')")

    created = 0
    for dept_code, (username, email, full_name) in DEPT_FACULTY_ACCOUNTS.items():
        if query_one("SELECT id FROM users WHERE username=?", (username,)):
            continue
        execute(
            "INSERT INTO users (username, email, password_hash, role, full_name, branch, profile_complete) "
            "VALUES (?,?,?,?,?,?,1)",
            (username, email, generate_password_hash(DEFAULT_FACULTY_PASSWORD), "faculty", full_name, dept_code)
        )
        created += 1
    if created:
        print(f"  ✅ Created {created} department-scoped faculty accounts (password: {DEFAULT_FACULTY_PASSWORD})")


def seed_departments_and_courses():
    """Seed all departments, courses, and proper course structure.

    Uses a SINGLE connection for the whole batch instead of opening a new
    connection per insert -- this was the root cause of the
    'database is locked' errors during seeding.
    """
    admin = query_one("SELECT id FROM users WHERE role='admin' LIMIT 1")
    faculty_users = query_all("SELECT id, branch FROM users WHERE role='faculty'")

    if not admin or not faculty_users:
        print("❌ Admin or Faculty users not found. Seed default users first!")
        return

    admin_id = admin["id"]
    faculty_ids = [f["id"] for f in faculty_users]

    # Group faculty by their department so each course is assigned to a
    # faculty member who actually teaches in that department, instead of a
    # random faculty member from anywhere in the university.
    faculty_by_dept = {}
    for f in faculty_users:
        if f["branch"]:
            faculty_by_dept.setdefault(f["branch"], []).append(f["id"])

    courses_created = 0

    conn = get_connection()
    cur = conn.cursor()

    # For each department
    for dept_code, dept_info in IGDTUW_DEPARTMENTS.items():
        print(f"\n📚 Seeding {dept_info['name']} ({dept_code})...")

        # FIXED: loop over every semester actually defined (1-6), not just
        # one semester per "year". The old code did
        #   semester = (year - 1) * 2 + 1
        # which only ever produces 1, 3, 5, 7 — silently skipping 2, 4, 6
        # (which the dict defines) and looking up a nonexistent semester 7.
        for semester in ALL_SEMESTERS:
            subjects = dept_info["semesters"].get(semester, [])

            for idx, subject in enumerate(subjects, 1):
                code = f"{dept_code}-{subject.replace(' ', '')[:8]}-S{semester}"

                try:
                    cur.execute(
                        """INSERT INTO courses
                        (name, code, subject, semester, department, section, academic_year, credits, created_by)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (subject, code, subject, semester, dept_code, "A", "2026-27", 4, admin_id)
                    )
                    course_id = cur.lastrowid

                    # Assign faculty to course -- prefer a faculty member
                    # from the same department; only fall back to "anyone"
                    # if that department has no dedicated faculty account.
                    dept_pool = faculty_by_dept.get(dept_code, faculty_ids)
                    faculty_id = random.choice(dept_pool)
                    cur.execute(
                        "INSERT INTO course_faculty (course_id, faculty_id) VALUES (?,?)",
                        (course_id, faculty_id)
                    )

                    courses_created += 1
                    print(f"  ✓ {subject} (Sem {semester})")
                except Exception as e:
                    print(f"  ⚠ Skipped {subject} (Sem {semester}): {str(e)[:40]}")

    conn.commit()
    conn.close()
    print(f"\n✅ Total courses created: {courses_created}")

def seed_students_per_course():
    """Seed STUDENTS_PER_BATCH realistic students per department/year and
    enroll them in every course for their (department, semester) — where
    semester is derived from year the same way the rest of the app does:
        year = (semester + 1) // 2   <=>   semesters {1,2}->year1, {3,4}->year2, {5,6}->year3

    Uses a SINGLE connection for the whole batch, with commits at each
    department+year checkpoint, instead of opening/closing a new
    connection for every one of the individual inserts.
    """
    admin = query_one("SELECT id FROM users WHERE role='admin' LIMIT 1")
    admin_id = admin["id"] if admin else 1

    total_students = 0
    total_enrollments = 0

    conn = get_connection()
    cur = conn.cursor()

    # Years covered by the 6 defined semesters: 1 -> sem 1&2, 2 -> sem 3&4, 3 -> sem 5&6
    years_covered = [1, 2, 3]

    for dept_code in IGDTUW_DEPARTMENTS.keys():
        for year in years_covered:
            print(f"\n👥 Generating {STUDENTS_PER_BATCH} students for {dept_code} Year {year}...")

            students_data = generate_students_for_course(dept_code, year, count=STUDENTS_PER_BATCH)

            for student in students_data:
                try:
                    cur.execute(
                        """INSERT INTO students
                        (roll_number, full_name, email, department, year, section, cgpa, phone, created_by)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            student["roll_number"],
                            student["full_name"],
                            student["email"],
                            student["department"],
                            student["year"],
                            student["section"],
                            student["cgpa"],
                            student["phone"],
                            admin_id
                        )
                    )
                    total_students += 1
                except Exception as e:
                    if "UNIQUE constraint failed" not in str(e):
                        print(f"  ⚠ Error inserting {student['roll_number']}: {str(e)[:40]}")

            conn.commit()

            # This year covers TWO semesters (e.g. year 1 -> semesters 1 and 2)
            sem_pair = [(year - 1) * 2 + 1, (year - 1) * 2 + 2]

            students_for_enroll = cur.execute(
                "SELECT id FROM students WHERE department=? AND year=?",
                (dept_code, year)
            ).fetchall()

            enrolled_this_batch = 0
            for semester in sem_pair:
                courses = cur.execute(
                    "SELECT id FROM courses WHERE department=? AND semester=?",
                    (dept_code, semester)
                ).fetchall()

                for course in courses:
                    # Cap enrollment per course at STUDENTS_PER_BATCH instead
                    # of enrolling every student in the dept+year batch into
                    # every one of that semester's courses -- that's what
                    # was silently blowing enrollments-per-course way past
                    # STUDENTS_PER_BATCH even though students_for_enroll
                    # itself was already capped at generation time.
                    pool = students_for_enroll
                    if len(pool) > STUDENTS_PER_BATCH:
                        pool = random.sample(pool, STUDENTS_PER_BATCH)

                    for student in pool:
                        try:
                            cur.execute(
                                "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?,?)",
                                (course["id"], student["id"])
                            )
                            total_enrollments += 1
                            enrolled_this_batch += 1
                        except Exception:
                            pass

            conn.commit()
            print(f"  ✅ Created {len(students_data)} students, "
                  f"enrolled across semesters {sem_pair} ({enrolled_this_batch} links)")

    conn.close()
    print(f"\n📊 Statistics:")
    print(f"  Total Students Created: {total_students}")
    print(f"  Total Enrollments: {total_enrollments}")

def seed_sample_attendance():
    """Seed sample attendance data for testing.

    Uses a single connection for the whole batch (this loop can generate
    thousands of inserts -- 300 enrollments x 20 days).
    """
    print("\n📋 Seeding sample attendance records...")

    enrollments = query_all("""
        SELECT e.id, e.student_id, c.subject, c.id as course_id
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        LIMIT 300
    """)

    marked_by_row = query_one("SELECT id FROM users WHERE role='faculty' LIMIT 1")
    if not marked_by_row:
        print("  ❌ No faculty user found, skipping attendance seeding.")
        return
    marked_by = marked_by_row["id"]

    base_date = datetime.now() - timedelta(days=30)
    attendance_count = 0

    conn = get_connection()
    cur = conn.cursor()

    for i, enrollment in enumerate(enrollments):
        for day in range(1, 21):
            date = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
            status = "present" if random.random() > 0.25 else "absent"

            try:
                cur.execute(
                    """INSERT OR IGNORE INTO attendance
                    (student_id, subject, date, status, marked_by)
                    VALUES (?,?,?,?,?)""",
                    (enrollment["student_id"], enrollment["subject"], date, status, marked_by)
                )
                attendance_count += 1
            except Exception:
                pass

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  ... {attendance_count} records seeded")

    conn.commit()
    conn.close()
    print(f"  ✅ Total attendance records: {attendance_count}")

if __name__ == "__main__":
    print("=" * 70)
    print("IGDTUW 2026-27 CURRICULUM & STUDENT DATA SEEDING")
    print("=" * 70)

    print("\n[1/4] Seeding department-scoped faculty accounts...")
    seed_department_faculty()

    print("\n[2/4] Seeding departments and courses...")
    seed_departments_and_courses()

    print(f"\n[3/4] Generating {STUDENTS_PER_BATCH} students per course...")
    seed_students_per_course()

    print("\n[4/4] Seeding sample attendance...")
    seed_sample_attendance()

    print("\n" + "=" * 70)
    print("✅ SEEDING COMPLETE!")
    print("=" * 70)