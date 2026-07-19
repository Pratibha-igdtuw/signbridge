from flask import Blueprint, request, jsonify

from database import db, Gesture
from auth import login_required, current_user

gesture_bp = Blueprint('gesture', __name__)


@gesture_bp.route('/api/gestures', methods=['GET'])
@login_required
def list_gestures():
    user = current_user()
    defaults = Gesture.query.filter_by(user_id=None).all()
    custom = Gesture.query.filter_by(user_id=user.id).all()
    return jsonify([g.to_dict() for g in defaults + custom])


@gesture_bp.route('/api/gestures', methods=['POST'])
@login_required
def add_gesture():
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    key = (data.get('gesture_key') or '').strip().upper().replace(' ', '_')
    word = (data.get('word') or '').strip()
    emoji = (data.get('emoji') or '\U0001f590').strip()

    if not key or not word:
        return jsonify({'error': 'gesture_key and word are required'}), 400
    if len(key) > 50 or len(word) > 120:
        return jsonify({'error': 'gesture_key or word is too long'}), 400

    exists = Gesture.query.filter_by(gesture_key=key, user_id=user.id).first()
    if exists:
        return jsonify({'error': 'You already have a custom gesture with this key'}), 409

    g = Gesture(gesture_key=key, word=word, emoji=emoji, is_custom=True, user_id=user.id)
    db.session.add(g)
    db.session.commit()
    return jsonify({'message': 'Gesture added', 'gesture': g.to_dict()}), 201


@gesture_bp.route('/api/gestures/<gesture_key>', methods=['DELETE'])
@login_required
def delete_gesture(gesture_key):
    user = current_user()
    g = Gesture.query.filter_by(gesture_key=gesture_key.upper(), user_id=user.id).first()
    if not g:
        return jsonify({'error': 'Custom gesture not found'}), 404
    db.session.delete(g)
    db.session.commit()
    return jsonify({'message': 'Gesture deleted'})
