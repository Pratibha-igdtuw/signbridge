"""
Database Schema Updates & Migration Notes
For Bulk Attendance Marking v2
"""

# ============================================================================
# NO BREAKING CHANGES REQUIRED ✅
# ============================================================================
# The new bulk attendance implementation is 100% compatible with existing
# database.py schema. All required tables already exist:
#
# ✓ users
# ✓ students  
# ✓ courses
# ✓ course_faculty
# ✓ enrollments
# ✓ attendance
# ✓ activity_logs
#

# ============================================================================
# OPTIONAL: Schema Enhancements (Recommended but not required)
# ============================================================================

# 1. Add indexes for better query performance
PERFORMANCE_INDEXES = """
-- Speed up attendance queries by date
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);

-- Speed up course lookups by department
CREATE INDEX IF NOT EXISTS idx_courses_dept_sem ON courses(department, semester);

-- Speed up enrollment lookups
CREATE INDEX IF NOT EXISTS idx_enrollments_course ON enrollments(course_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_student ON enrollments(student_id);

-- Speed up student lookups by department
CREATE INDEX IF NOT EXISTS idx_students_dept ON students(department, year);

-- Activity logging indexes
CREATE INDEX IF NOT EXISTS idx_activity_logs_user ON activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp);
"""

# 2. Add column to track attendance marked by faculty
# (This helps track which faculty marked attendance)
# Already exists in current schema but adding for clarity:

ATTENDANCE_TABLE_INFO = """
-- Current attendance table structure:
CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject     TEXT NOT NULL,
    date        TEXT NOT NULL,
    status      TEXT NOT NULL CHECK(status IN ('present','absent')),
    marked_by   INTEGER REFERENCES users(id),  -- ← Faculty/Admin who marked
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, subject, date)
);

-- marked_by is already in your schema ✅
"""

# 3. Optional: Add audit trail columns for compliance
AUDIT_COLUMNS = """
-- If you want to track who modified attendance records:
ALTER TABLE attendance ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE attendance ADD COLUMN updated_by INTEGER REFERENCES users(id);

-- For compliance tracking:
ALTER TABLE attendance ADD COLUMN approved_by INTEGER REFERENCES users(id);
ALTER TABLE attendance ADD COLUMN approved_at DATETIME;
"""

# ============================================================================
# Migration Function for Database
# ============================================================================

def apply_performance_optimizations(conn=None):
    """
    Apply performance indexes and optimizations
    Call this once to speed up queries
    """
    from database import get_connection
    
    if conn is None:
        conn = get_connection()
    
    cur = conn.cursor()
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)",
        "CREATE INDEX IF NOT EXISTS idx_courses_dept_sem ON courses(department, semester)",
        "CREATE INDEX IF NOT EXISTS idx_enrollments_course ON enrollments(course_id)",
        "CREATE INDEX IF NOT EXISTS idx_enrollments_student ON enrollments(student_id)",
        "CREATE INDEX IF NOT EXISTS idx_students_dept ON students(department, year)",
        "CREATE INDEX IF NOT EXISTS idx_activity_logs_user ON activity_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp)",
    ]
    
    for idx_sql in indexes:
        try:
            cur.execute(idx_sql)
            print(f"✓ {idx_sql.split('idx_')[1].split(' ')[0]}")
        except Exception as e:
            print(f"⚠ Index creation: {str(e)[:50]}")
    
    conn.commit()
    if conn:
        conn.close()
    
    print("\n✅ Performance indexes applied!")


# ============================================================================
# Data Integrity Checks
# ============================================================================

def verify_data_integrity():
    """
    Verify data integrity after seeding
    Run this to check everything is correct
    """
    from database import query_one
    
    checks = {
        "Users": "SELECT COUNT(*) as count FROM users",
        "Students": "SELECT COUNT(*) as count FROM students",
        "Courses": "SELECT COUNT(*) as count FROM courses",
        "Enrollments": "SELECT COUNT(*) as count FROM enrollments",
        "Attendance Records": "SELECT COUNT(*) as count FROM attendance",
    }
    
    print("📊 Data Integrity Check:\n")
    for check_name, sql in checks.items():
        result = query_one(sql)
        count = result['count'] if result else 0
        status = "✓" if count > 0 else "⚠"
        print(f"{status} {check_name:20s}: {count:,} records")
    
    # Detailed checks
    print("\n🔍 Detailed Validation:\n")
    
    # Check 1: Orphaned students (students not in any course)
    orphaned = query_one("""
        SELECT COUNT(*) as count FROM students s
        WHERE NOT EXISTS (
            SELECT 1 FROM enrollments e WHERE e.student_id = s.id
        )
    """)
    if orphaned['count'] > 0:
        print(f"⚠ Orphaned students (not enrolled): {orphaned['count']}")
    else:
        print("✓ All students are enrolled in courses")
    
    # Check 2: Courses without faculty
    no_faculty = query_one("""
        SELECT COUNT(*) as count FROM courses c
        WHERE NOT EXISTS (
            SELECT 1 FROM course_faculty cf WHERE cf.course_id = c.id
        )
    """)
    if no_faculty['count'] > 0:
        print(f"⚠ Courses without faculty: {no_faculty['count']}")
    else:
        print("✓ All courses have assigned faculty")
    
    # Check 3: Invalid attendance records
    invalid_att = query_one("""
        SELECT COUNT(*) as count FROM attendance
        WHERE status NOT IN ('present', 'absent')
    """)
    if invalid_att['count'] > 0:
        print(f"⚠ Invalid attendance status: {invalid_att['count']}")
    else:
        print("✓ All attendance records have valid status")
    
    # Check 4: Attendance without marked_by
    unmarked = query_one("""
        SELECT COUNT(*) as count FROM attendance
        WHERE marked_by IS NULL
    """)
    print(f"ℹ Attendance records without marked_by: {unmarked['count']}")
    
    print("\n✅ Integrity check complete!")


# ============================================================================
# Rollback/Cleanup Functions
# ============================================================================

def delete_test_data():
    """
    Delete all seeded test data (use with caution!)
    Only use if something went wrong during seeding
    """
    from database import execute, get_connection
    
    conn = get_connection()
    
    print("⚠️  Deleting test data...")
    
    # Delete in order of dependencies
    execute("DELETE FROM attendance")
    print("✓ Attendance records deleted")
    
    execute("DELETE FROM enrollments")
    print("✓ Enrollments deleted")
    
    execute("DELETE FROM course_faculty")
    print("✓ Course faculty assignments deleted")
    
    execute("DELETE FROM courses WHERE academic_year = '2026-27'")
    print("✓ Courses deleted")
    
    execute("DELETE FROM students")
    print("✓ Students deleted")
    
    execute("DELETE FROM activity_logs WHERE module = 'Attendance'")
    print("✓ Activity logs cleaned")
    
    conn.close()
    print("\n✅ Test data deleted!")


# ============================================================================
# Usage Examples in Python
# ============================================================================

"""
# In your Flask app or management script:

from database import get_connection
from database_updates import apply_performance_optimizations, verify_data_integrity

# Apply optimizations (run once)
apply_performance_optimizations()

# Verify everything is correct (run anytime)
verify_data_integrity()

# Only if you need to clean up:
# from database_updates import delete_test_data
# delete_test_data()
"""

# ============================================================================
# SQL Queries for Manual Verification
# ============================================================================

VERIFICATION_QUERIES = {
    "Total Students by Department": """
        SELECT department, COUNT(*) as count 
        FROM students 
        GROUP BY department 
        ORDER BY count DESC;
    """,
    
    "Courses per Department": """
        SELECT department, COUNT(DISTINCT id) as count 
        FROM courses 
        GROUP BY department 
        ORDER BY department;
    """,
    
    "Students per Course": """
        SELECT c.name, COUNT(e.student_id) as enrollment_count
        FROM courses c
        LEFT JOIN enrollments e ON c.id = e.course_id
        GROUP BY c.id
        ORDER BY enrollment_count DESC
        LIMIT 10;
    """,
    
    "Attendance Summary": """
        SELECT 
            DATE(date) as date,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent
        FROM attendance
        GROUP BY DATE(date)
        ORDER BY date DESC
        LIMIT 10;
    """,
    
    "Faculty Load": """
        SELECT 
            u.full_name,
            COUNT(DISTINCT cf.course_id) as courses_assigned
        FROM users u
        LEFT JOIN course_faculty cf ON u.id = cf.faculty_id
        WHERE u.role = 'faculty'
        GROUP BY u.id;
    """,
}

# ============================================================================
# Quick Start
# ============================================================================

if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════════╗
    ║   Database Schema & Migration Guide                            ║
    ║   Bulk Attendance Marking v2                                   ║
    ╚════════════════════════════════════════════════════════════════╝
    
    STATUS: ✅ No breaking changes - fully compatible!
    
    OPTIONAL OPTIMIZATIONS:
    1. Run: apply_performance_optimizations()
       → Adds indexes for faster queries
    
    2. Run: verify_data_integrity()
       → Checks everything is correct
    
    USAGE:
    ------
    from database_updates import apply_performance_optimizations
    apply_performance_optimizations()
    
    QUICK SQL CHECKS:
    ----------------
    """)
    
    for check_name, query in VERIFICATION_QUERIES.items():
        print(f"  • {check_name}")
    
    print("""
    
    For more info, see SETUP_GUIDE.md
    """)