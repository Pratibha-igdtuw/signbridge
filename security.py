"""
Security utilities.

Brings together the defensive techniques taught across the lab:
  - Input validation              (Experiments 1-9 "Secure Fix")
  - Whitelisting                  (Experiments 3, 9, 10 -> ORDER BY / enum fields)
  - SQL Injection detection rule  (Experiment 13)

These run *in addition* to parameterized queries. Parameterization alone stops
classic injection; validation + whitelisting handle the cases parameters can't
(e.g. column names in ORDER BY can never be bound as a parameter), and the
detector turns blocked attempts into forensic alerts.
"""
import re

# ----------------------------------------------------------------------------
# Whitelists -- the only acceptable values for fields that can't be bound.
# A column name in ORDER BY is SQL structure, not data, so it must be checked
# against an allow-list rather than passed as a "?" parameter.
# ----------------------------------------------------------------------------
ALLOWED_SORT_COLUMNS = {
    "roll_number", "full_name", "department", "year", "section", "cgpa", "created_at",
}
ALLOWED_SORT_DIRECTIONS = {"ASC", "DESC"}
ALLOWED_DEPARTMENTS = {"CSE", "ME", "ECE", "CE", "EE", "IT", "AIML"}
ALLOWED_ROLES = {"admin", "faculty", "student"}


# ----------------------------------------------------------------------------
# Experiment 13: detection rule for SQL Injection attempts.
# We do NOT rely on this to *prevent* injection (parameterization does that);
# we use it to *detect and alert* on malicious input for the audit trail.
# ----------------------------------------------------------------------------
SUSPICIOUS_PATTERNS = [
    r"('|\")\s*(or|and)\s*('|\")?\d",   # ' OR '1, ' OR 1
    r"\bunion\b\s+\bselect\b",          # UNION SELECT
    r"--",                              # comment terminator
    r";\s*drop\b",                      # ; DROP
    r";\s*delete\b",                    # ; DELETE
    r"\bsleep\s*\(",                    # time-based
    r"\bbenchmark\s*\(",
    r"\bwaitfor\s+delay\b",
    r"\bor\b\s+1\s*=\s*1",              # OR 1=1
    r"\binformation_schema\b",
    r"\bxp_cmdshell\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in SUSPICIOUS_PATTERNS]


def looks_like_injection(value: str) -> bool:
    """Return True if the input matches a known SQL-injection signature."""
    if not isinstance(value, str):
        return False
    return any(rx.search(value) for rx in _COMPILED)


# ----------------------------------------------------------------------------
# Field validators -- reject malformed input early (defence in depth).
# ----------------------------------------------------------------------------
_ROLL = re.compile(r"^[A-Za-z0-9]{4,20}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,30}$")
_PHONE = re.compile(r"^[0-9]{10}$")
_NAME = re.compile(r"^[A-Za-z .'-]{2,60}$")
_SECTION = re.compile(r"^[A-Za-z][A-Za-z0-9]?$")


def validate_student(form):
    """Validate a student record. Returns (cleaned_dict, errors_list)."""
    errors = []
    roll = (form.get("roll_number") or "").strip()
    name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip()
    dept = (form.get("department") or "").strip().upper()
    year = (form.get("year") or "").strip()
    section = (form.get("section") or "A").strip().upper()
    cgpa = (form.get("cgpa") or "").strip()
    phone = (form.get("phone") or "").strip()

    if not _ROLL.match(roll):
        errors.append("Roll number must be 4-20 letters/digits.")
    if not _NAME.match(name):
        errors.append("Name must be 2-60 letters.")
    if not _EMAIL.match(email):
        errors.append("Email is not valid.")
    if dept not in ALLOWED_DEPARTMENTS:
        errors.append(f"Department must be one of {', '.join(sorted(ALLOWED_DEPARTMENTS))}.")
    if not _SECTION.match(section):
        errors.append("Section must be 1-2 letters/digits (e.g. A, B, C1).")
    try:
        year_i = int(year)
        if year_i < 1 or year_i > 5:
            errors.append("Year must be between 1 and 5.")
    except ValueError:
        year_i = None
        errors.append("Year must be a number.")
    try:
        cgpa_f = float(cgpa) if cgpa else None
        if cgpa_f is not None and not (0 <= cgpa_f <= 10):
            errors.append("CGPA must be between 0 and 10.")
    except ValueError:
        cgpa_f = None
        errors.append("CGPA must be a number.")
    if phone and not _PHONE.match(phone):
        errors.append("Phone must be 10 digits.")

    cleaned = {
        "roll_number": roll, "full_name": name, "email": email,
        "department": dept, "year": year_i, "section": section,
        "cgpa": cgpa_f, "phone": phone,
    }
    return cleaned, errors


def validate_registration(form):
    errors = []
    username = (form.get("username") or "").strip()
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""
    full_name = (form.get("full_name") or "").strip()
    role = (form.get("role") or "student").strip()

    if not _USERNAME.match(username):
        errors.append("Username must be 3-30 letters/digits/underscore.")
    if not _EMAIL.match(email):
        errors.append("Email is not valid.")
    if not _NAME.match(full_name):
        errors.append("Name must be 2-60 letters.")
    if role not in ALLOWED_ROLES:
        errors.append("Invalid role.")
    # Password strength
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    elif not (re.search(r"[A-Z]", password) and re.search(r"[a-z]", password)
              and re.search(r"\d", password)):
        errors.append("Password needs upper, lower and a digit.")

    cleaned = {"username": username, "email": email, "password": password,
               "full_name": full_name, "role": role}
    return cleaned, errors


def safe_sort(column, direction):
    """Whitelist ORDER BY parts. Falls back to a safe default on bad input."""
    col = column if column in ALLOWED_SORT_COLUMNS else "created_at"
    dir_ = direction.upper() if direction and direction.upper() in ALLOWED_SORT_DIRECTIONS else "DESC"
    return col, dir_
