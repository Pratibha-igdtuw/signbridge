"""
Pytest fixtures for IDon Portal v3 Enhanced tests.
"""
import os
import pytest
import tempfile

os.environ.setdefault("MAIL_SUPPRESS_SEND", "true")


@pytest.fixture
def app():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    # Use a temp DB so tests are isolated
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    # Patch Config before importing app
    from config import Config
    Config.DB_PATH = db_path
    Config.WTF_CSRF_ENABLED = False

    import database as db
    db.init_db()
    db.migrate_db()
    conn = db.get_connection()
    db.migrate_v3(conn)
    conn.close()
    db.seed()

    import app as app_module
    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    flask_app.config["SERVER_NAME"] = "localhost"

    yield flask_app

    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(client):
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    return client


@pytest.fixture
def student_client(client):
    client.post("/login", data={"username": "student", "password": "Student@123"})
    return client


@pytest.fixture
def faculty_client(client):
    client.post("/login", data={"username": "faculty", "password": "Faculty@123"})
    return client
