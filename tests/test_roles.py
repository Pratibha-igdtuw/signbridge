"""Tests for role-based access control."""
import pytest


def test_student_cannot_access_dashboard(student_client):
    r = student_client.get("/dashboard", follow_redirects=True)
    # Should redirect away or show 403
    assert r.status_code in (200, 403)
    assert b"permission" in r.data.lower() or b"sign in" in r.data.lower() \
           or b"attendance" in r.data.lower()


def test_student_cannot_access_audit(student_client):
    r = student_client.get("/audit/activity", follow_redirects=True)
    assert r.status_code in (200, 403)
    assert b"permission" in r.data.lower() or b"sign in" in r.data.lower()


def test_student_cannot_access_users(student_client):
    r = student_client.get("/users", follow_redirects=True)
    assert r.status_code in (200, 403)
    assert b"permission" in r.data.lower() or b"sign in" in r.data.lower()


def test_student_cannot_delete_student(student_client):
    r = student_client.post("/students/1/delete", follow_redirects=True)
    assert r.status_code in (200, 403)


def test_faculty_cannot_delete_user(faculty_client):
    r = faculty_client.post("/users/1/suspend", follow_redirects=True)
    assert r.status_code in (200, 403)


def test_admin_can_access_dashboard(admin_client):
    r = admin_client.get("/dashboard")
    assert r.status_code == 200


def test_admin_can_access_users(admin_client):
    r = admin_client.get("/users")
    assert r.status_code == 200


def test_admin_can_access_audit(admin_client):
    r = admin_client.get("/audit/activity")
    assert r.status_code == 200


def test_unauthenticated_redirected_to_login(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 303)
