from flask import Blueprint, request, jsonify

from database import db, PracticeAttempt, Translation
from auth import login_required, current_user
from translate_routes import _get_or_create_active_conversation
from emergency_routes import _get_or_create_emergency_conversation
from learn_content import get_lesson

sync_bp = Blueprint('sync', __name__)


@sync_bp.route('/api/sync', methods=['POST'])
@login_required
def sync_offline_queue():
    """
    Body: {
      translations: [{source, text, gesture_key}],
      emergency_logs: [{source, text, gesture_key}],
      practice_attempts: [{lesson_key, detected_gesture, confidence}],
    }
    Each list is optional. Items are validated the same way their live endpoints
    validate them; anything invalid is skipped and reported back rather than
    failing the whole batch, since a stale offline queue shouldn't block sync.
    """
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    counts = {'translations': 0, 'emergency_logs': 0, 'practice_attempts': 0}
    skipped = 0

    translations = data.get('translations') or []
    if translations:
        conv = _get_or_create_active_conversation(user.id)
        for item in translations:
            source = item.get('source')
            text = (item.get('text') or '').strip()
            if source not in ('sign', 'voice', 'text') or not text:
                skipped += 1
                continue
            db.session.add(Translation(
                conversation_id=conv.id, source=source, gesture_key=item.get('gesture_key'), text=text,
            ))
            counts['translations'] += 1

    emergency_logs = data.get('emergency_logs') or []
    if emergency_logs:
        conv = _get_or_create_emergency_conversation(user.id)
        for item in emergency_logs:
            source = item.get('source')
            text = (item.get('text') or '').strip()
            if source not in ('sign', 'voice', 'text') or not text:
                skipped += 1
                continue
            db.session.add(Translation(
                conversation_id=conv.id, source=source, gesture_key=item.get('gesture_key'), text=text,
            ))
            counts['emergency_logs'] += 1

    practice_attempts = data.get('practice_attempts') or []
    for item in practice_attempts:
        lesson = get_lesson(item.get('lesson_key'))
        if not lesson:
            skipped += 1
            continue
        detected = item.get('detected_gesture')
        correct = (detected == lesson['gesture_key']) if lesson['detectable'] else None
        db.session.add(PracticeAttempt(
            user_id=user.id, category=lesson['category'], lesson_key=lesson['key'],
            expected_gesture=lesson['gesture_key'], detected_gesture=detected,
            confidence=item.get('confidence'), correct=correct,
        ))
        counts['practice_attempts'] += 1

    db.session.commit()
    return jsonify({'message': 'Synced Successfully', 'synced': counts, 'skipped': skipped}), 200