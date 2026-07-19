def test_register_success(client):
    res = client.post('/api/auth/register', json={
        'name': 'Alice', 'email': 'alice@example.com', 'password': 'Password1'
    })
    assert res.status_code == 201
    assert res.get_json()['user']['email'] == 'alice@example.com'


def test_register_weak_password(client):
    res = client.post('/api/auth/register', json={
        'name': 'Alice', 'email': 'alice@example.com', 'password': 'weak'
    })
    assert res.status_code == 400


def test_register_duplicate_email(client):
    client.post('/api/auth/register', json={
        'name': 'Alice', 'email': 'alice@example.com', 'password': 'Password1'
    })
    res = client.post('/api/auth/register', json={
        'name': 'Bob', 'email': 'alice@example.com', 'password': 'Password1'
    })
    assert res.status_code == 409


def test_login_success(client):
    client.post('/api/auth/register', json={
        'name': 'Alice', 'email': 'alice@example.com', 'password': 'Password1'
    })
    client.post('/api/auth/logout')
    res = client.post('/api/auth/login', json={
        'email': 'alice@example.com', 'password': 'Password1'
    })
    assert res.status_code == 200


def test_login_wrong_password(client):
    client.post('/api/auth/register', json={
        'name': 'Alice', 'email': 'alice@example.com', 'password': 'Password1'
    })
    client.post('/api/auth/logout')
    res = client.post('/api/auth/login', json={
        'email': 'alice@example.com', 'password': 'WrongPass1'
    })
    assert res.status_code == 401


def test_me_requires_login(client):
    res = client.get('/api/auth/me')
    assert res.get_json()['user'] is None


def test_logout_clears_session(registered_client):
    registered_client.post('/api/auth/logout')
    res = registered_client.get('/api/translate', json={})
    assert res.status_code in (401, 405)
