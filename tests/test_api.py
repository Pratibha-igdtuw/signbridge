def test_translate_requires_login(client):
    res = client.post('/api/translate', json={'source': 'sign', 'text': 'Hello'})
    assert res.status_code == 401


def test_log_and_fetch_translation(registered_client):
    res = registered_client.post('/api/translate', json={
        'source': 'sign', 'text': 'Hello', 'gesture_key': 'OPEN_HAND'
    })
    assert res.status_code == 201

    res = registered_client.get('/api/history')
    data = res.get_json()
    assert len(data) == 1
    assert data[0]['text'] == 'Hello'


def test_translate_invalid_source(registered_client):
    res = registered_client.post('/api/translate', json={'source': 'telepathy', 'text': 'Hi'})
    assert res.status_code == 400


def test_default_gestures_present(registered_client):
    res = registered_client.get('/api/gestures')
    keys = [g['gesture_key'] for g in res.get_json()]
    assert 'OPEN_HAND' in keys
    assert 'ILY' in keys


def test_add_custom_gesture(registered_client):
    res = registered_client.post('/api/gestures', json={
        'gesture_key': 'OK Sign', 'word': 'Okay', 'emoji': '👌'
    })
    assert res.status_code == 201
    assert res.get_json()['gesture']['gesture_key'] == 'OK_SIGN'


def test_duplicate_custom_gesture_rejected(registered_client):
    registered_client.post('/api/gestures', json={'gesture_key': 'OK', 'word': 'Okay'})
    res = registered_client.post('/api/gestures', json={'gesture_key': 'OK', 'word': 'Okay again'})
    assert res.status_code == 409


def test_stats_reflect_logged_translations(registered_client):
    registered_client.post('/api/translate', json={'source': 'sign', 'text': 'Hello', 'gesture_key': 'OPEN_HAND'})
    registered_client.post('/api/translate', json={'source': 'voice', 'text': 'Hi there'})

    res = registered_client.get('/api/stats')
    data = res.get_json()
    assert data['total_translations'] == 2
    assert data['by_source']['sign'] == 1
    assert data['by_source']['voice'] == 1


def test_clear_history(registered_client):
    registered_client.post('/api/translate', json={'source': 'voice', 'text': 'Hi'})
    registered_client.delete('/api/history')
    res = registered_client.get('/api/history')
    assert res.get_json() == []
