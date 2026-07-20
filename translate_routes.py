from flask import Blueprint, request, jsonify

from database import db, Conversation, Translation
from auth import login_required, current_user

translate_bp = Blueprint('translate', __name__)


def _get_or_create_active_conversation(user_id):
    conv = Conversation.query.filter_by(user_id=user_id).order_by(Conversation.id.desc()).first()
    if not conv:
        conv = Conversation(user_id=user_id, title='Conversation 1')
        db.session.add(conv)
        db.session.commit()
    return conv


@translate_bp.route('/api/conversations', methods=['GET'])
@login_required
def list_conversations():
    user = current_user()
    convs = Conversation.query.filter_by(user_id=user.id).order_by(Conversation.id.desc()).all()
    return jsonify([
        {'id': c.id, 'title': c.title, 'created_at': c.created_at.isoformat()} for c in convs
    ])


@translate_bp.route('/api/conversations/new', methods=['POST'])
@login_required
def new_conversation():
    user = current_user()
    count = Conversation.query.filter_by(user_id=user.id).count()
    conv = Conversation(user_id=user.id, title=f'Conversation {count + 1}')
    db.session.add(conv)
    db.session.commit()
    return jsonify({'conversation_id': conv.id, 'title': conv.title}), 201


@translate_bp.route('/api/translate', methods=['POST'])
@login_required
def log_translation():
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    source = data.get('source')
    text = (data.get('text') or '').strip()
    gesture_key = data.get('gesture_key')
    conversation_id = data.get('conversation_id')

    if source not in ('sign', 'voice', 'text') or not text:
        return jsonify({'error': "source must be 'sign', 'voice', or 'text', and text is required"}), 400

    if conversation_id:
        conv = Conversation.query.filter_by(id=conversation_id, user_id=user.id).first()
        if not conv:
            return jsonify({'error': 'Invalid conversation_id'}), 404
    else:
        conv = _get_or_create_active_conversation(user.id)

    t = Translation(conversation_id=conv.id, source=source, gesture_key=gesture_key, text=text)
    db.session.add(t)
    db.session.commit()
    return jsonify({'message': 'logged', 'translation': t.to_dict(), 'conversation_id': conv.id}), 201


@translate_bp.route('/api/history', methods=['GET'])
@login_required
def history():
    user = current_user()
    conv_id = request.args.get('conversation_id', type=int)
    limit = request.args.get('limit', 200, type=int)

    q = Translation.query.join(Conversation).filter(Conversation.user_id == user.id)
    if conv_id:
        q = q.filter(Translation.conversation_id == conv_id)
    rows = q.order_by(Translation.id.desc()).limit(limit).all()
    return jsonify([t.to_dict() for t in reversed(rows)])


@translate_bp.route('/api/history', methods=['DELETE'])
@login_required
def clear_history():
    user = current_user()
    conv_id = request.args.get('conversation_id', type=int)

    conv_ids = [c.id for c in Conversation.query.filter_by(user_id=user.id).all()]
    if conv_id:
        conv_ids = [conv_id] if conv_id in conv_ids else []

    if conv_ids:
        Translation.query.filter(Translation.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.session.commit()
    return jsonify({'message': 'history cleared'})
