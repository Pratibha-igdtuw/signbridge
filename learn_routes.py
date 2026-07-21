from flask import Blueprint, request, jsonify, render_template, abort

from database import db, PracticeAttempt
from auth import login_required, current_user
from learn_content import CATEGORIES, LESSONS, lessons_by_category, get_lesson
from progress_utils import practice_stats

learn_bp = Blueprint('learn', __name__)


# ---------- Pages ----------

@learn_bp.route('/learn')
@login_required
def learn_page():
    return render_template(
        'learn.html', user=current_user(), active='learn',
        categories=CATEGORIES, grouped=lessons_by_category(),
    )


@learn_bp.route('/learn/practice/<lesson_key>')
@login_required
def practice_page(lesson_key):
    lesson = get_lesson(lesson_key)
    if not lesson:
        abort(404)
    return render_template('practice.html', user=current_user(), active='learn', lesson=lesson)


@learn_bp.route('/learn/progress')
@login_required
def learn_progress_page():
    return render_template('learn_progress.html', user=current_user(), active='learn')


# ---------- API ----------

@learn_bp.route('/api/learn/lessons', methods=['GET'])
@login_required
def api_lessons():
    user = current_user()

    # Per-lesson "completed" = at least one correct attempt ever.
    completed_keys = {
        row.lesson_key for row in
        PracticeAttempt.query.filter_by(user_id=user.id, correct=True)
        .with_entities(PracticeAttempt.lesson_key).distinct()
    }

    out = []
    for lesson in LESSONS:
        item = dict(lesson)
        item['completed'] = lesson['key'] in completed_keys
        out.append(item)
    return jsonify({'categories': CATEGORIES, 'lessons': out})


@learn_bp.route('/api/practice/attempt', methods=['POST'])
@login_required
def log_practice_attempt():
    """
    Log one practice attempt for a lesson. If the lesson has a detectable gesture,
    `detected_gesture` is compared to the lesson's expected gesture to decide
    correct/incorrect. If the lesson isn't detectable yet, the attempt is stored
    as unscored (correct = null) so it still counts toward streaks/sessions
    without pretending we scored something we can't actually recognize.
    """
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    lesson_key = data.get('lesson_key')
    detected = data.get('detected_gesture')
    confidence = data.get('confidence')

    lesson = get_lesson(lesson_key)
    if not lesson:
        return jsonify({'error': 'Unknown lesson_key'}), 400

    try:
        confidence = float(confidence) if confidence is not None else None
        if confidence is not None:
            confidence = max(0.0, min(100.0, confidence))
    except (TypeError, ValueError):
        confidence = None

    correct = None
    if lesson['detectable']:
        correct = bool(detected) and detected == lesson['gesture_key']

    attempt = PracticeAttempt(
        user_id=user.id,
        category=lesson['category'],
        lesson_key=lesson_key,
        expected_gesture=lesson['gesture_key'],
        detected_gesture=detected,
        confidence=confidence,
        correct=correct,
    )
    db.session.add(attempt)
    db.session.commit()

    scored = PracticeAttempt.query.filter_by(
        user_id=user.id, lesson_key=lesson_key
    ).filter(PracticeAttempt.correct.isnot(None))
    total_scored = scored.count()
    correct_scored = scored.filter_by(correct=True).count()
    success_rate = round((correct_scored / total_scored) * 100, 1) if total_scored else None

    return jsonify({
        'message': 'attempt logged',
        'attempt': attempt.to_dict(),
        'detectable': lesson['detectable'],
        'attempts_for_lesson': PracticeAttempt.query.filter_by(user_id=user.id, lesson_key=lesson_key).count(),
        'success_rate_for_lesson': success_rate,
    }), 201


@learn_bp.route('/api/learn/progress', methods=['GET'])
@login_required
def learn_progress():
    user = current_user()
    stats = practice_stats(user.id)
    stats.pop('_attempts', None)
    # Keep the 'accuracy' key name this page originally used, alongside the
    # shared 'practice_accuracy' name used elsewhere, for template convenience.
    stats['accuracy'] = stats['practice_accuracy']
    return jsonify(stats)