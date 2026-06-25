# IDon Portal — Secure SMS v2

## New Features Added

### From your WhatsApp notes:
1. **Session management** — already in v1, now surfaced in Login History with entry_hash + username + role per row
2. **Attendance tracking** — `/attendance` page with per-subject stats and ⚠️ < 75% alert banner
3. **SGPA Calculator** — `/sgpa` — fully client-side, grade → points reference table, 5 subjects by default
4. **Assignments by faculty + Homework by students** — `/assignments`; faculty upload with dept/year filter; students submit from modal; faculty see all submissions
5. **Password eye toggle** — login, register, and change-password all have 👁️ / 🙈 toggle
6. **Login History with entry_hash, username, role** — SHA-256 tamper-evident hash in every login row; visible in `/audit/logins`
7. **Profile setup on first login** — new users are redirected to `/profile/setup` to fill: name, email, contact no., branch, university, year
8. **Change password** — available in `/profile` settings page
9. **Students removed from Dashboard sidebar** — students land directly on Attendance; no dashboard link in their nav

### Extra features included:
- **Dashboard low-attendance table** — admin/faculty see all students < 75% attendance at a glance
- **Profile page** — edit personal info and change password from one place
- **Role-aware navigation** — sidebar adapts per role (admin/faculty/student)

## Setup

```bash
pip install -r requirements.txt
python app.py
```

## Demo accounts
| Role    | Username | Password   |
|---------|----------|------------|
| Admin   | admin    | Admin@123  |
| Faculty | faculty  | Faculty@123|
| Student | student  | Student@123|

## Routes
| Route | Access | Purpose |
|-------|--------|---------|
| `/` | All | Redirect by role |
| `/login` | Public | Sign in |
| `/register` | Public | Create account |
| `/profile/setup` | Logged in (first login) | Complete profile |
| `/profile` | Logged in | Edit info + change password |
| `/dashboard` | Admin, Faculty | Stats, charts, alerts |
| `/attendance` | All | View/mark attendance |
| `/sgpa` | All | SGPA calculator |
| `/assignments` | All | Upload (faculty) / Submit homework (student) |
| `/students` | All | CRUD student records |
| `/files` | Admin, Faculty | General file management |
| `/audit/*` | Admin only | Forensic audit logs |
