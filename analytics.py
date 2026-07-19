from flask import Blueprint, jsonify, render_template
from sqlalchemy import func

from database import db, Translation, Conversation, LoginEvent
from auth import login_required, current_user

analytics_bp = Blueprint('analytics', __name__)


# ---------- Pages ----------

@analytics_bp.route('/dashboard')
@login_required
def dashboard_page():
    return render_template('dashboard.html', user=current_user())


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


# ---------- API ----------

@analytics_bp.route('/api/stats', methods=['GET'])
@login_required
def stats():
    user = current_user()

    total = (
        db.session.query(func.count(Translation.id))
        .join(Conversation)
        .filter(Conversation.user_id == user.id)
        .scalar()
    ) or 0

    by_source = (
        db.session.query(Translation.source, func.count(Translation.id))
        .join(Conversation)
        .filter(Conversation.user_id == user.id)
        .group_by(Translation.source)
        .all()
    )

    top_gestures = (
        db.session.query(Translation.gesture_key, func.count(Translation.id).label('c'))
        .join(Conversation)
        .filter(
            Conversation.user_id == user.id,
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

    return jsonify({
        'total_translations': total,
        'by_source': {s: c for s, c in by_source},
        'top_gestures': [{'gesture_key': g, 'count': c} for g, c in top_gestures],
        'total_logins': total_logins,
        'total_conversations': total_conversations,
    })
