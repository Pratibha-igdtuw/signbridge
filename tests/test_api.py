"""Tests for the JWT API layer."""
import json
import pytest


def _get_token(client, username="admin", password="Admin@123"):
    r = client.post("/api/token",
                    json={"username": username, "password": password})
    if r.status_code == 200:
        return r.get_json().get("token")
    return None


def test_api_token_issued_for_valid_creds(client):
    r = client.post("/api/token",
                    json={"username": "admin", "password": "Admin@123"})
    assert r.status_code == 200
    data = r.get_json()
    assert "token" in data


def test_api_token_rejected_for_bad_creds(client):
    r = client.post("/api/token",
                    json={"username": "admin", "password": "wrongpass"})
    assert r.status_code in (401, 400)


def test_api_students_requires_jwt(client):
    r = client.get("/api/students")
    assert r.status_code == 401


def test_api_students_returns_list(client):
    token = _get_token(client)
    if token is None:
        pytest.skip("Could not get API token")
    r = client.get("/api/students",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)


def test_api_alert_count_requires_login(client):
    r = client.get("/api/alert-count")
    assert r.status_code in (302, 401)
