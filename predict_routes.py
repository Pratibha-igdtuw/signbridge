from flask import Blueprint, request, jsonify

from database import Translation, Conversation
from auth import login_required, current_user
from prediction_engine import predict_from_gesture_sequence, predict_reply

predict_bp = Blueprint('predict', __name__)


def _recent_context_words(user_id, conversation_id, limit=6):
    """Pulls the last few words/phrases already said in this conversation, so
    predictions can use context beyond just the single latest gesture."""
    if not conversation_id:
        return []
    rows = (
        Translation.query.join(Conversation)
        .filter(Conversation.user_id == user_id, Translation.conversation_id == conversation_id)
        .order_by(Translation.id.desc())
        .limit(limit)
        .all()
    )
    words = []
    for t in reversed(rows):
        words.extend(t.text.split())
    return words


@predict_bp.route('/api/predict/gesture', methods=['POST'])
@login_required
def predict_gesture():
    """
    Body: { history: ["I", "Want", "Water"], conversation_id?: int }
    Returns ranked sentence suggestions for what the signer is likely saying.
    """
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    history = data.get('history') or []
    conversation_id = data.get('conversation_id')

    if not isinstance(history, list) or not history:
        return jsonify({'suggestions': []})

    context = _recent_context_words(user.id, conversation_id)
    # Blend prior conversation words with the live gesture history so a sequence
    # like "I" (said 2 turns ago) + "Want" + "Water" (just signed) can still match.
    combined = (context + [str(h) for h in history])[-6:]

    suggestions = predict_from_gesture_sequence(combined, limit=3)
    if not suggestions:
        suggestions = predict_from_gesture_sequence(history, limit=3)
    return jsonify({'suggestions': suggestions})


@predict_bp.route('/api/predict/reply', methods=['POST'])
@login_required
def predict_reply_route():
    """
    Body: { transcript: "Where are you going?", conversation_id?: int }
    Returns quick-reply chips for what the Deaf user might want to say back.
    """
    data = request.get_json(force=True, silent=True) or {}
    transcript = (data.get('transcript') or '').strip()
    if not transcript:
        return jsonify({'suggestions': []})
    return jsonify({'suggestions': predict_reply(transcript, limit=4)})