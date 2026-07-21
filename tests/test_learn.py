def test_lessons_list_requires_login(client):
    res = client.get('/api/learn/lessons')
    assert res.status_code == 401


def test_lessons_list(registered_client):
    res = registered_client.get('/api/learn/lessons')
    assert res.status_code == 200
    data = res.get_json()
    assert len(data['lessons']) > 0
    assert all('detectable' in l for l in data['lessons'])


def test_practice_attempt_correct_and_incorrect(registered_client):
    ok = registered_client.post('/api/practice/attempt', json={
        'lesson_key': 'GREET_HELLO', 'detected_gesture': 'OPEN_HAND', 'confidence': 88
    })
    assert ok.status_code == 201
    assert ok.get_json()['attempt']['correct'] is True

    bad = registered_client.post('/api/practice/attempt', json={
        'lesson_key': 'GREET_HELLO', 'detected_gesture': 'FIST', 'confidence': 30
    })
    assert bad.status_code == 201
    assert bad.get_json()['attempt']['correct'] is False


def test_practice_attempt_unscored_for_non_detectable_lesson(registered_client):
    res = registered_client.post('/api/practice/attempt', json={
        'lesson_key': 'EMG_HELP', 'detected_gesture': None, 'confidence': None
    })
    assert res.status_code == 201
    body = res.get_json()
    assert body['detectable'] is False
    assert body['attempt']['correct'] is None


def test_practice_attempt_unknown_lesson_rejected(registered_client):
    res = registered_client.post('/api/practice/attempt', json={'lesson_key': 'NOPE'})
    assert res.status_code == 400


def test_learn_progress_reflects_attempts(registered_client):
    registered_client.post('/api/practice/attempt', json={
        'lesson_key': 'GREET_HELLO', 'detected_gesture': 'OPEN_HAND', 'confidence': 90
    })
    registered_client.post('/api/practice/attempt', json={
        'lesson_key': 'DAILY_WAIT', 'detected_gesture': 'ONE', 'confidence': 80
    })
    res = registered_client.get('/api/learn/progress')
    data = res.get_json()
    assert data['lessons_completed'] == 2
    assert data['total_practice_sessions'] == 2
    assert data['daily_streak'] == 1


def test_learn_pages_render(registered_client):
    assert registered_client.get('/learn').status_code == 200
    assert registered_client.get('/learn/practice/GREET_HELLO').status_code == 200
    assert registered_client.get('/learn/practice/NOPE').status_code == 404
    assert registered_client.get('/learn/progress').status_code == 200