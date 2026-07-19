import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import create_app
from config import TestConfig
from database import db


@pytest.fixture
def app():
    app = create_app(TestConfig)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered_client(client):
    client.post('/api/auth/register', json={
        'name': 'Test User',
        'email': 'test@example.com',
        'password': 'Password1'
    })
    return client
