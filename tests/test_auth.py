"""Tests for authentication: login, register, lockout, approval workflow."""
import pytest


def test_login_valid_admin(admin_client):
    r = admin_client.get("/dashboard", follow_redirects=True)
    assert r.status_code == 200
    assert b"Dashboard" in r.data or b"IDon" in r.data


def test_login_valid_faculty(faculty_client):
    r = faculty_client.get("/dashboard", follow_redirects=True)
    assert r.status_code == 200


def test_login_valid_student(student_client):
    r = student_client.get("/attendance", follow_redirects=True)
    assert r.status_code == 200


def test_login_invalid_password(client):
    r = client.post("/login",
                    data={"username": "admin", "password": "wrongpassword"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"Invalid" in r.data or b"credentials" in r.data


def test_login_wrong_user(client):
    r = client.post("/login",
                    data={"username": "nobody", "password": "whatever"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"Invalid" in r.data or b"credentials" in r.data


def test_login_lockout_after_5_fails(client):
    """After 5 failed logins the account should be locked."""
    for _ in range(5):
        client.post("/login",
                    data={"username": "student", "password": "badpass"})
    r = client.post("/login",
                    data={"username": "student", "password": "badpass"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"locked" in r.data.lower() or b"too many" in r.data.lower()


def test_register_pending_status(client, app):
    r = client.post("/register", data={
        "username": "newstu",
        "email": "newstu@igdtuw.ac.in",
        "password": "NewPass1",
        "full_name": "New Student",
        "role": "student",
    }, follow_redirects=True)
    assert r.status_code == 200
    # Login should be blocked (pending)
    r2 = client.post("/login",
                     data={"username": "newstu", "password": "NewPass1"},
                     follow_redirects=True)
    assert b"pending" in r2.data.lower() or b"approval" in r2.data.lower()


def test_logout(admin_client):
    r = admin_client.get("/logout", follow_redirects=True)
    assert r.status_code == 200
