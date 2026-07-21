from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, Response
import json

from database import db, Conversation, Translation
from auth import login_required, current_user

live_bp = Blueprint('live', __name__)


def _get_or_create_live_conversation(user_id):
    """Live Conversation gets its own conversation (mode='live'), kept separate from
    the ordinary For You transcript and Emergency Mode sessions."""
    conv = Conversation.query.filter_by(user_id=user_id, mode='live') \
        .order_by(Conversation.id.desc()).first()
    if not conv:
        conv = Conversation(user_id=user_id, title='Live Conversation', mode='live')
        db.session.add(conv)
        db.session.commit()
    return conv


@live_bp.route('/live')
@login_required
def live_page():
    return render_template('live.html', user=current_user(), active='live')


@live_bp.route('/api/live/conversation', methods=['GET'])
@login_required
def live_conversation():
    """Returns (creating if needed) the user's live conversation id + its messages."""
    user = current_user()
    conv = _get_or_create_live_conversation(user.id)
    rows = Translation.query.filter_by(conversation_id=conv.id).order_by(Translation.id.asc()).all()
    return jsonify({'conversation_id': conv.id, 'messages': [t.to_dict() for t in rows]})


@live_bp.route('/api/live/send', methods=['POST'])
@login_required
def live_send():
    """
    Logs one message in the Live Conversation.
    sender: 'hearing' (left side) or 'deaf' (right side)
    source: 'speech' (hearing person talking) or 'sign' (deaf user signing) or 'text' (typed reply)
    """
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    sender = data.get('sender')
    source = data.get('source')
    text = (data.get('text') or '').strip()
    gesture_key = data.get('gesture_key')

    if sender not in ('hearing', 'deaf'):
        return jsonify({'error': "sender must be 'hearing' or 'deaf'"}), 400
    # Translation.source is constrained to sign|voice|text elsewhere in the app;
    # map the Live Conversation's 'speech' concept onto the existing 'voice' value.
    if source == 'speech':
        source = 'voice'
    if source not in ('sign', 'voice', 'text') or not text:
        return jsonify({'error': "source must be 'sign', 'voice'/'speech', or 'text', and text is required"}), 400

    conv = _get_or_create_live_conversation(user.id)
    t = Translation(conversation_id=conv.id, source=source, gesture_key=gesture_key, text=text, sender=sender)
    db.session.add(t)
    db.session.commit()
    return jsonify({'message': 'sent', 'translation': t.to_dict(), 'conversation_id': conv.id}), 201


@live_bp.route('/api/live/messages', methods=['DELETE'])
@login_required
def live_clear():
    user = current_user()
    conv = Conversation.query.filter_by(user_id=user.id, mode='live').order_by(Conversation.id.desc()).first()
    if conv:
        Translation.query.filter_by(conversation_id=conv.id).delete()
        db.session.commit()
    return jsonify({'message': 'conversation cleared'})


@live_bp.route('/api/live/export', methods=['GET'])
@login_required
def live_export():
    """Exports the live conversation transcript as a downloadable JSON file."""
    user = current_user()
    conv = Conversation.query.filter_by(user_id=user.id, mode='live').order_by(Conversation.id.desc()).first()
    rows = []
    if conv:
        rows = Translation.query.filter_by(conversation_id=conv.id).order_by(Translation.id.asc()).all()
    payload = json.dumps({'exported_at': datetime.utcnow().isoformat(),
                           'messages': [t.to_dict() for t in rows]}, indent=2)
    return Response(
        payload, mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=signbridge_live_conversation.json'},
    )