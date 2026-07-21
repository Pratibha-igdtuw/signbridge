from flask import Blueprint, request, jsonify, render_template

from database import db, Conversation, Translation
from auth import login_required, current_user

emergency_bp = Blueprint('emergency', __name__)

# Large, high-contrast quick-communication buttons shown in Emergency Mode.
QUICK_PHRASES = [
    "I Need Help", "Call an Ambulance", "Call the Police", "I Am Deaf",
    "Please Speak Slowly", "Thank You", "Yes", "No", "Water", "Doctor",
]


def _get_or_create_emergency_conversation(user_id):
    """Emergency sessions get their own conversation (mode='emergency') so they never
    mix into the ordinary For You transcript or the Live Conversation history."""
    conv = Conversation.query.filter_by(user_id=user_id, mode='emergency') \
        .order_by(Conversation.id.desc()).first()
    if not conv:
        conv = Conversation(user_id=user_id, title='Emergency session', mode='emergency')
        db.session.add(conv)
        db.session.commit()
    return conv


@emergency_bp.route('/emergency')
@login_required
def emergency_page():
    return render_template('emergency.html', user=current_user(), active='emergency', phrases=QUICK_PHRASES)


@emergency_bp.route('/api/emergency/log', methods=['POST'])
@login_required
def log_emergency_message():
    """Logs a quick-phrase tap, typed message, or voice/sign capture made while in
    Emergency Mode. Reuses the same Translation table as the rest of the app so it
    shows up in Analytics, just tagged to an 'emergency' conversation."""
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    source = data.get('source', 'text')
    text = (data.get('text') or '').strip()
    gesture_key = data.get('gesture_key')

    if source not in ('sign', 'voice', 'text') or not text:
        return jsonify({'error': "source must be 'sign', 'voice', or 'text', and text is required"}), 400

    conv = _get_or_create_emergency_conversation(user.id)
    t = Translation(conversation_id=conv.id, source=source, gesture_key=gesture_key, text=text)
    db.session.add(t)
    db.session.commit()
    return jsonify({'message': 'logged', 'translation': t.to_dict(), 'conversation_id': conv.id}), 201


@emergency_bp.route('/api/emergency/history', methods=['GET'])
@login_required
def emergency_history():
    user = current_user()
    conv = Conversation.query.filter_by(user_id=user.id, mode='emergency') \
        .order_by(Conversation.id.desc()).first()
    if not conv:
        return jsonify([])
    rows = Translation.query.filter_by(conversation_id=conv.id).order_by(Translation.id.asc()).all()
    return jsonify([t.to_dict() for t in rows])