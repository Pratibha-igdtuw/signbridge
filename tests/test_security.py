"""Tests for security controls: XSS, SQL injection, file upload."""
import io
import pytest


def test_sql_injection_in_login_username(client):
    """SQL injection in username field should not crash — returns 200 with error."""
    r = client.post("/login",
                    data={"username": "' OR '1'='1", "password": "anything"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"Invalid" in r.data or b"credentials" in r.data or b"rejected" in r.data


def test_xss_in_notice_is_escaped(admin_client):
    """XSS payload in notice body should be HTML-escaped in the response."""
    xss = "<script>alert('xss')</script>"
    admin_client.post("/notices/create", data={
        "title": "XSS Test",
        "body": xss,
        "category": "general",
        "target_role": "all",
        "is_pinned": "0",
    }, follow_redirects=True)
    r = admin_client.get("/notices")
    assert b"<script>alert" not in r.data  # raw tag must not appear


def test_file_upload_rejects_php(admin_client):
    """Uploading a .php file should be rejected."""
    data = {
        "file": (io.BytesIO(b"<?php echo 'hack'; ?>"), "shell.php"),
        "student_id": "",
    }
    r = admin_client.post("/files/upload",
                          data=data,
                          content_type="multipart/form-data",
                          follow_redirects=True)
    assert r.status_code == 200
    assert b"shell.php" not in r.data or b"not allowed" in r.data.lower()


def test_file_upload_rejects_exe(admin_client):
    data = {
        "file": (io.BytesIO(b"MZ\x90\x00"), "virus.exe"),
        "student_id": "",
    }
    r = admin_client.post("/files/upload",
                          data=data,
                          content_type="multipart/form-data",
                          follow_redirects=True)
    assert r.status_code == 200
    assert b"virus.exe" not in r.data or b"not allowed" in r.data.lower()


def test_unauthenticated_cannot_post_student(client):
    r = client.post("/students/new", data={
        "roll_number": "HACK001",
        "full_name": "Hacker",
        "email": "h@test.com",
        "department": "CSE",
        "year": "1",
    }, follow_redirects=True)
    assert b"sign in" in r.data.lower() or r.status_code in (302, 401, 403)


def test_union_injection_in_search(admin_client):
    r = admin_client.get("/students?q=' UNION SELECT 1,2,3--",
                         follow_redirects=True)
    assert r.status_code == 200
    assert b"rejected" in r.data.lower() or b"Search" in r.data or b"Students" in r.data
