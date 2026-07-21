def test_predict_gesture_single_word(registered_client):
    res = registered_client.post('/api/predict/gesture', json={'history': ['Hello']})
    assert res.status_code == 200
    suggestions = res.get_json()['suggestions']
    assert len(suggestions) > 0
    assert all('text' in s and 'confidence' in s for s in suggestions)
    # Ranked by confidence, most confident first
    confidences = [s['confidence'] for s in suggestions]
    assert confidences == sorted(confidences, reverse=True)


def test_predict_gesture_sequence_more_specific_than_single_word(registered_client):
    res = registered_client.post('/api/predict/gesture', json={'history': ['I', 'Want', 'Water']})
    suggestions = res.get_json()['suggestions']
    assert any('water' in s['text'].lower() for s in suggestions)


def test_predict_gesture_empty_history(registered_client):
    res = registered_client.post('/api/predict/gesture', json={'history': []})
    assert res.status_code == 200
    assert res.get_json()['suggestions'] == []


def test_predict_reply_matches_pattern(registered_client):
    res = registered_client.post('/api/predict/reply', json={'transcript': 'Where are you going?'})
    suggestions = res.get_json()['suggestions']
    assert any('home' in s['text'].lower() for s in suggestions)


def test_predict_reply_falls_back_to_generic(registered_client):
    res = registered_client.post('/api/predict/reply', json={'transcript': 'completely unrelated statement'})
    assert res.status_code == 200
    assert len(res.get_json()['suggestions']) > 0


def test_predict_requires_login(client):
    res = client.post('/api/predict/gesture', json={'history': ['Hello']})
    assert res.status_code == 401


def test_sync_offline_queue(registered_client):
    res = registered_client.post('/api/sync', json={
        'translations': [{'source': 'sign', 'text': 'Hello', 'gesture_key': 'OPEN_HAND'}],
        'emergency_logs': [{'source': 'text', 'text': 'I Need Help'}],
        'practice_attempts': [{'lesson_key': 'GREET_HELLO', 'detected_gesture': 'OPEN_HAND', 'confidence': 90}],
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body['synced'] == {'translations': 1, 'emergency_logs': 1, 'practice_attempts': 1}
    assert body['skipped'] == 0

    # Confirm they actually landed in the right, isolated places.
    history = registered_client.get('/api/history').get_json()
    assert any(t['text'] == 'Hello' for t in history)
    emg = registered_client.get('/api/emergency/history').get_json()
    assert any(t['text'] == 'I Need Help' for t in emg)
    progress = registered_client.get('/api/learn/progress').get_json()
    assert progress['total_practice_sessions'] == 1


def test_sync_skips_invalid_items_without_failing_batch(registered_client):
    res = registered_client.post('/api/sync', json={
        'translations': [{'source': 'bogus', 'text': ''}],
        'practice_attempts': [{'lesson_key': 'NOT_REAL'}],
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body['synced'] == {'translations': 0, 'emergency_logs': 0, 'practice_attempts': 0}
    assert body['skipped'] == 2


def test_sync_requires_login(client):
    res = client.post('/api/sync', json={})
    assert res.status_code == 401