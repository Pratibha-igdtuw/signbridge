def test_emergency_page_requires_login(client):
    res = client.get('/emergency')
    assert res.status_code in (302, 401)


def test_emergency_page_renders(registered_client):
    res = registered_client.get('/emergency')
    assert res.status_code == 200
    assert b'I Need Help' in res.data


def test_emergency_log_and_history(registered_client):
    res = registered_client.post('/api/emergency/log', json={'source': 'text', 'text': 'I Need Help'})
    assert res.status_code == 201

    hist = registered_client.get('/api/emergency/history')
    assert hist.status_code == 200
    rows = hist.get_json()
    assert len(rows) == 1
    assert rows[0]['text'] == 'I Need Help'


def test_emergency_log_rejects_bad_source(registered_client):
    res = registered_client.post('/api/emergency/log', json={'source': 'nope', 'text': 'hi'})
    assert res.status_code == 400


def test_emergency_conversation_isolated_from_regular_chat(registered_client):
    registered_client.post('/api/translate', json={'source': 'text', 'text': 'normal chat message'})
    registered_client.post('/api/emergency/log', json={'source': 'text', 'text': 'emergency message'})

    history = registered_client.get('/api/history').get_json()
    emg_history = registered_client.get('/api/emergency/history').get_json()

    assert any(t['text'] == 'normal chat message' for t in history)
    assert not any(t['text'] == 'emergency message' for t in history)
    assert any(t['text'] == 'emergency message' for t in emg_history)


def test_live_conversation_flow(registered_client):
    empty = registered_client.get('/api/live/conversation').get_json()
    assert empty['messages'] == []

    sent = registered_client.post('/api/live/send', json={
        'sender': 'hearing', 'source': 'speech', 'text': 'Hello there'
    })
    assert sent.status_code == 201
    assert sent.get_json()['translation']['source'] == 'voice'  # speech maps onto existing 'voice' value
    assert sent.get_json()['translation']['sender'] == 'hearing'

    registered_client.post('/api/live/send', json={
        'sender': 'deaf', 'source': 'sign', 'text': 'Hello', 'gesture_key': 'OPEN_HAND'
    })

    convo = registered_client.get('/api/live/conversation').get_json()
    assert len(convo['messages']) == 2

    export = registered_client.get('/api/live/export')
    assert export.status_code == 200
    assert 'attachment' in export.headers.get('Content-Disposition', '')

    cleared = registered_client.delete('/api/live/messages')
    assert cleared.status_code == 200
    convo_after = registered_client.get('/api/live/conversation').get_json()
    assert convo_after['messages'] == []


def test_live_send_requires_valid_sender(registered_client):
    res = registered_client.post('/api/live/send', json={'sender': 'nobody', 'source': 'text', 'text': 'hi'})
    assert res.status_code == 400