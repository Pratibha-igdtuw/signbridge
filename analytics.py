from datetime import datetime

from flask import Blueprint, jsonify, render_template, abort
from sqlalchemy import func

from database import db, Translation, Conversation, LoginEvent, PracticeAttempt
from auth import login_required, current_user
from explore_content import ARTICLES
from progress_utils import (
    practice_stats, weekly_activity, average_session_duration_minutes,
    recent_activity_timeline, recognition_accuracy,
)

analytics_bp = Blueprint('analytics', __name__)


# ---------- Pages ----------

@analytics_bp.route('/dashboard')
@login_required
def dashboard_page():
    return render_template('dashboard.html', user=current_user(), articles=ARTICLES)


@analytics_bp.route('/for-you')
@login_required
def for_you_page():
    return render_template('for_you.html', user=current_user())


@analytics_bp.route('/learn/asl')
@login_required
def learn_asl_page():
    return render_template('learn_asl.html', user=current_user())


@analytics_bp.route('/learn/bsl')
@login_required
def learn_bsl_page():
    return render_template('learn_bsl.html', user=current_user())


@analytics_bp.route('/explore/<slug>')
@login_required
def explore_article_page(slug):
    article = ARTICLES.get(slug)
    if not article:
        abort(404)
    return render_template('explore_article.html', user=current_user(), article=article, slug=slug)


@analytics_bp.route('/history')
@login_required
def history_page():
    return render_template('history.html', user=current_user())


@analytics_bp.route('/gestures-page')
@login_required
def gestures_page():
    return render_template('gestures.html', user=current_user())


@analytics_bp.route('/analytics-page')
@login_required
def analytics_page():
    return render_template('analytics.html', user=current_user())


@analytics_bp.route('/about')
@login_required
def about_page():
    return render_template('about.html', user=current_user(), active='about')


# ---------- API ----------

@analytics_bp.route('/api/stats', methods=['GET'])
@login_required
def stats():
    user = current_user()

    total = (
        db.session.query(func.count(Translation.id))
        .join(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.mode == 'chat')
        .scalar()
    ) or 0

    by_source = (
        db.session.query(Translation.source, func.count(Translation.id))
        .join(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.mode == 'chat')
        .group_by(Translation.source)
        .all()
    )

    top_gestures = (
        db.session.query(Translation.gesture_key, func.count(Translation.id).label('c'))
        .join(Conversation)
        .filter(
            Conversation.user_id == user.id,
            Conversation.mode == 'chat',
            Translation.source == 'sign',
            Translation.gesture_key.isnot(None),
        )
        .group_by(Translation.gesture_key)
        .order_by(func.count(Translation.id).desc())
        .limit(5)
        .all()
    )

    total_logins = LoginEvent.query.filter_by(user_id=user.id, success=True).count()
    total_conversations = Conversation.query.filter_by(user_id=user.id).count()

    # ---- Extended metrics (Feature 5: User Progress & Analytics) ----
    today = datetime.utcnow().date()
    all_translations = (
        Translation.query.join(Conversation).filter(Conversation.user_id == user.id, Conversation.mode == 'chat').all()
    )
    daily_translations = sum(1 for t in all_translations if t.created_at.date() == today)

    p_stats = practice_stats(user.id)
    attempts = p_stats.pop('_attempts')

    return jsonify({
        # ---- original fields (unchanged, existing consumers keep working) ----
        'total_translations': total,
        'by_source': {s: c for s, c in by_source},
        'top_gestures': [{'gesture_key': g, 'count': c} for g, c in top_gestures],
        'total_logins': total_logins,
        'total_conversations': total_conversations,

        # ---- new fields ----
        'daily_translations': daily_translations,
        'weekly_activity': weekly_activity(user.id),
        'recognition_accuracy': recognition_accuracy(user.id),  # avg detector confidence from scored Practice Mode attempts
        'practice_accuracy': p_stats['practice_accuracy'],
        'daily_streak': p_stats['daily_streak'],
        'lessons_completed': p_stats['lessons_completed'],
        'total_lessons': p_stats['total_lessons'],
        'total_practice_sessions': p_stats['total_practice_sessions'],
        'top_categories_learned': p_stats['top_categories'],
        'average_session_duration_minutes': average_session_duration_minutes(user.id, all_translations, attempts),
        'recent_activity': recent_activity_timeline(user.id),
    })