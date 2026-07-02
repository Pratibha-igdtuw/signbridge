"""
Flask Routes for Bulk Attendance Marking - v2 (Restructured)
Add these routes to your main Flask app (app.py)
"""

from flask import Blueprint, request, jsonify, render_template
from database import query_all, query_one, execute
from functools import wraps
from datetime import datetime
import json

# Create blueprint
attendance_bp = Blueprint('attendance', __name__, url_prefix='/api')

# ============================================================================
# Authentication Decorator (use your existing auth)
# ============================================================================
def require_role(*roles):
    """Decorator to check user role"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Replace with your actual auth check
            # This is a placeholder - adjust to your auth mechanism
            user_role = request.headers.get('X-User-Role', 'guest')
            if user_role not in roles:
                return jsonify({"error": "Unauthorized"}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ============================================================================
# API Endpoints
# ============================================================================

@attendance_bp.route('/courses-by-dept/<dept>', methods=['GET'])
@require_role('admin', 'faculty')
def get_courses_by_department(dept):
    """
    Get all courses organized by semester for a department
    Returns: { semester: [{ id, name, subject, credits }] }
    """
    try:
        courses = query_all("""
            SELECT 
                id, 
                name, 
                code,
                subject,
                semester,
                credits,
                section
            FROM courses 
            WHERE department = ? 
            ORDER BY semester ASC, name ASC
        """, (dept,))
        
        # Organize by semester
        by_semester = {}
        for course in courses:
            sem = course['semester']
            if sem not in by_semester:
                by_semester[sem] = []
            by_semester[sem].append({
                'id': course['id'],
                'name': course['name'],
                'code': course['code'],
                'subject': course['subject'],
                'semester': sem,
                'credits': course['credits'],
                'section': course['section']
            })
        
        return jsonify(by_semester), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@attendance_bp.route('/students-in-course/<int:course_id>', methods=['GET'])
@require_role('admin', 'faculty')
def get_students_in_course(course_id):
    """
    Get all students enrolled in a course (up to 60)
    Returns: [{ id, full_name, roll_number, email, cgpa, department, year }]
    """
    try:
        students = query_all("""
            SELECT 
                s.id,
                s.full_name,
                s.roll_number,
                s.email,
                s.cgpa,
                s.department,
                s.year,
                s.phone
            FROM students s
            JOIN enrollments e ON s.id = e.student_id
            WHERE e.course_id = ?
            ORDER BY s.roll_number ASC
            LIMIT 60
        """, (course_id,))
        
        return jsonify([dict(s) for s in students]), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@attendance_bp.route('/attendance/bulk-mark', methods=['POST'])
@require_role('admin', 'faculty')
def bulk_mark_attendance():
    """
    Mark attendance for multiple students at once
    
    Request body:
    {
        "course_id": int,
        "subject": string,
        "date": "YYYY-MM-DD",
        "attendance": { student_id: "present"|"absent", ... }
    }
    """
    try:
        data = request.get_json()
        
        # Validate input
        if not all(k in data for k in ['course_id', 'subject', 'date', 'attendance']):
            return jsonify({"error": "Missing required fields"}), 400
        
        course_id = data.get('course_id')
        subject = data.get('subject')
        date_str = data.get('date')
        attendance_dict = data.get('attendance')
        
        # Validate date format
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Verify course exists
        course = query_one("SELECT id FROM courses WHERE id = ?", (course_id,))
        if not course:
            return jsonify({"error": "Course not found"}), 404
        
        # Get user ID (adjust based on your auth implementation)
        user_id = request.headers.get('X-User-ID', 1)  # Fallback to admin
        
        marked_count = 0
        errors = []
        
        # Insert attendance records
        for student_id_str, status in attendance_dict.items():
            if status not in ['present', 'absent']:
                errors.append(f"Invalid status for student {student_id_str}")
                continue
            
            try:
                student_id = int(student_id_str)
                
                # Check if student is enrolled
                enrollment = query_one("""
                    SELECT id FROM enrollments 
                    WHERE course_id = ? AND student_id = ?
                """, (course_id, student_id))
                
                if not enrollment:
                    errors.append(f"Student {student_id} not enrolled in this course")
                    continue
                
                # Insert or update attendance
                execute("""
                    INSERT OR REPLACE INTO attendance 
                    (student_id, subject, date, status, marked_by, created_at) 
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (student_id, subject, date_str, status, user_id))
                
                marked_count += 1
            
            except ValueError:
                errors.append(f"Invalid student ID: {student_id_str}")
            except Exception as e:
                errors.append(f"Error marking student {student_id_str}: {str(e)}")
        
        # Create activity log
        activity_log(user_id, 'attendance_bulk_marked', 'Attendance', 
                    f"Marked {marked_count} students in {subject} on {date_str}")
        
        response = {
            "success": True,
            "marked": marked_count,
            "date": date_str,
            "subject": subject,
            "message": f"Successfully marked {marked_count} students"
        }
        
        if errors:
            response["warnings"] = errors[:5]  # Return first 5 warnings
        
        return jsonify(response), 201
    
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


@attendance_bp.route('/attendance/by-date/<subject>/<date>', methods=['GET'])
@require_role('admin', 'faculty')
def get_attendance_by_date(subject, date):
    """
    Get all attendance records for a specific subject and date
    """
    try:
        records = query_all("""
            SELECT 
                a.id,
                a.student_id,
                s.full_name,
                s.roll_number,
                a.status,
                a.date,
                a.subject
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            WHERE a.subject = ? AND a.date = ?
            ORDER BY s.roll_number ASC
        """, (subject, date))
        
        return jsonify([dict(r) for r in records]), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@attendance_bp.route('/attendance/department-summary/<dept>/<date>', methods=['GET'])
@require_role('admin', 'faculty')
def get_department_attendance_summary(dept, date):
    """
    Get attendance summary for entire department on a specific date
    """
    try:
        summary = query_all("""
            SELECT 
                s.department,
                COUNT(DISTINCT s.id) as total_students,
                SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) as absent_count,
                SUM(CASE WHEN a.id IS NULL THEN 1 ELSE 0 END) as not_marked
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id AND a.date = ?
            WHERE s.department = ?
            GROUP BY s.department
        """, (date, dept))
        
        if summary:
            s = summary[0]
            return jsonify({
                "date": date,
                "department": dept,
                "total_students": s['total_students'],
                "present": s['present_count'],
                "absent": s['absent_count'],
                "not_marked": s['not_marked'],
                "attendance_percentage": round((s['present_count'] / s['total_students'] * 100) if s['total_students'] > 0 else 0, 2)
            }), 200
        
        return jsonify({"error": "No data found"}), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@attendance_bp.route('/attendance/course-report/<int:course_id>', methods=['GET'])
@require_role('admin', 'faculty')
def get_course_attendance_report(course_id):
    """
    Get attendance report for a course (all dates, all students)
    """
    try:
        # Get course info
        course = query_one("SELECT name, subject, semester, department FROM courses WHERE id = ?", (course_id,))
        if not course:
            return jsonify({"error": "Course not found"}), 404
        
        # Get students and their attendance
        students = query_all("""
            SELECT 
                s.id,
                s.full_name,
                s.roll_number,
                COUNT(DISTINCT CASE WHEN a.status = 'present' THEN a.date END) as present_days,
                COUNT(DISTINCT CASE WHEN a.status = 'absent' THEN a.date END) as absent_days,
                COUNT(DISTINCT a.date) as total_marked,
                ROUND(COUNT(DISTINCT CASE WHEN a.status = 'present' THEN a.date) * 100.0 / 
                      NULLIF(COUNT(DISTINCT a.date), 0), 2) as attendance_percentage
            FROM students s
            JOIN enrollments e ON s.id = e.student_id
            LEFT JOIN attendance a ON s.id = a.student_id AND a.subject = ?
            WHERE e.course_id = ?
            GROUP BY s.id
            ORDER BY s.roll_number ASC
        """, (course['subject'], course_id))
        
        return jsonify({
            "course": {
                "id": course_id,
                "name": course['name'],
                "subject": course['subject'],
                "semester": course['semester'],
                "department": course['department']
            },
            "students": [dict(s) for s in students],
            "summary": {
                "total_students": len(students),
                "average_attendance": round(
                    sum(s['attendance_percentage'] or 0 for s in students) / len(students) if students else 0, 2
                )
            }
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Activity Logging
# ============================================================================
def activity_log(user_id, action, module, details=""):
    """Log user activity"""
    try:
        execute("""
            INSERT INTO activity_logs (user_id, action, module, details, timestamp)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, action, module, details))
    except Exception as e:
        print(f"Error logging activity: {e}")


# ============================================================================
# Template Route (to serve the bulk attendance page)
# ============================================================================
@attendance_bp.route('/bulk-attendance', methods=['GET'])
@require_role('admin', 'faculty')
def bulk_attendance_page():
    """Serve the bulk attendance marking page"""
    return render_template('bulk_attendance_v2.html')


# ============================================================================
# To integrate into your Flask app (app.py):
# ============================================================================
"""
Add this to your main Flask app:

from attendance_routes import attendance_bp

app.register_blueprint(attendance_bp)

Also update your authentication headers to pass:
- X-User-Role: admin|faculty|student
- X-User-ID: (integer user id)
"""