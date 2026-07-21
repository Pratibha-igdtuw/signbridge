"""
Shared analytics/progress helpers. Centralized here so the Learn module's
progress dashboard and the main Analytics dashboard compute streaks, accuracy,
and activity the same way instead of drifting apart in two places.

Metrics here are only ever derived from data we actually store — nothing is
fabricated. Where we don't have enough data for a meaningful number (e.g. no
explicit session start/end timestamps), we compute a clearly-labelled
approximation instead of inventing a value.
"""
from datetime import timedelta, datetime

from database import Translation, Conversation, PracticeAttempt
from learn_content import LESSONS


def compute_streak(dates):
    """Given an iterable of date objects, return the current consecutive-day
    streak ending today or yesterday (so it doesn't zero out the moment the
    clock rolls over before someone's practiced today)."""
    days = sorted(set(dates), reverse=True)
    if not days:
        return 0
    today = datetime.utcnow().date()
    if days[0] not in (today, today - timedelta(days=1)):
        return 0
    streak = 0
    expected = days[0]
    for day in days:
        if day == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif day < expected:
            break
    return streak


def practice_stats(user_id):
    attempts = PracticeAttempt.query.filter_by(user_id=user_id).all()
    scored = [a for a in attempts if a.correct is not None]
    accuracy = round(sum(1 for a in scored if a.correct) / len(scored) * 100, 1) if scored else 0
    lessons_completed = len({a.lesson_key for a in attempts if a.correct})

    by_category = {}
    for a in attempts:
        slot = by_category.setdefault(a.category, {'attempts': 0, 'correct': 0})
        slot['attempts'] += 1
        if a.correct:
            slot['correct'] += 1
    top_categories = sorted(by_category.items(), key=lambda kv: kv[1]['attempts'], reverse=True)

    return {
        'lessons_completed': lessons_completed,
        'total_lessons': len(LESSONS),
        'practice_accuracy': accuracy,
        'daily_streak': compute_streak(a.created_at.date() for a in attempts),
        'total_practice_sessions': len(attempts),
        'top_categories': [{'category': k, **v} for k, v in top_categories[:5]],
        '_attempts': attempts,  # internal use by callers that also need raw rows
    }


def recognition_accuracy(user_id):
    """
    Average detector confidence (0-100) recorded during scored Practice Mode
    attempts — i.e. how confidently the camera recognizer matched a gesture
    when we actually know what gesture was expected. Returns None if the user
    hasn't done a scored practice attempt yet (nothing to average).
    """
    rows = (
        PracticeAttempt.query.filter_by(user_id=user_id)
        .filter(PracticeAttempt.correct.isnot(None), PracticeAttempt.confidence.isnot(None))
        .all()
    )
    if not rows:
        return None
    return round(sum(r.confidence for r in rows) / len(rows), 1)


def weekly_activity(user_id, days=7):
    """Translation counts for each of the last `days` calendar days (oldest first)."""
    today = datetime.utcnow().date()
    counts = {(today - timedelta(days=i)): 0 for i in range(days)}
    rows = (
        Translation.query.join(Conversation)
        .filter(Conversation.user_id == user_id, Conversation.mode == 'chat')
        .all()
    )
    for t in rows:
        d = t.created_at.date()
        if d in counts:
            counts[d] += 1
    ordered = sorted(counts.items())
    return [{'date': d.isoformat(), 'count': c} for d, c in ordered]


def average_session_duration_minutes(user_id, translations, practice_attempts):
    """
    Approximate average session length: for each calendar day with 2+ events
    (translations or practice attempts combined), duration = last event time
    minus first event time that day. Days with only one event are excluded
    (no way to estimate a span from a single point). Returns None if there's
    not enough data yet.
    """
    by_day = {}
    for row in list(translations) + list(practice_attempts):
        d = row.created_at.date()
        by_day.setdefault(d, []).append(row.created_at)

    spans = []
    for _, timestamps in by_day.items():
        if len(timestamps) < 2:
            continue
        span = (max(timestamps) - min(timestamps)).total_seconds() / 60.0
        if span > 0:
            spans.append(span)

    if not spans:
        return None
    return round(sum(spans) / len(spans), 1)


def recent_activity_timeline(user_id, limit=15):
    """Merges recent translations and practice attempts into one feed, newest first."""
    translations = (
        Translation.query.join(Conversation)
        .filter(Conversation.user_id == user_id, Conversation.mode == 'chat')
        .order_by(Translation.id.desc())
        .limit(limit)
        .all()
    )
    attempts = (
        PracticeAttempt.query.filter_by(user_id=user_id)
        .order_by(PracticeAttempt.id.desc())
        .limit(limit)
        .all()
    )

    events = []
    for t in translations:
        label = {'sign': 'Sign detected', 'voice': 'Voice transcribed', 'text': 'Typed to sign'}.get(t.source, 'Translation')
        events.append({'type': 'translation', 'label': label, 'detail': t.text, 'created_at': t.created_at})
    for a in attempts:
        if a.correct is True:
            label = 'Practice — correct'
        elif a.correct is False:
            label = 'Practice — try again'
        else:
            label = 'Practice session'
        events.append({'type': 'practice', 'label': label, 'detail': a.lesson_key, 'created_at': a.created_at})

    events.sort(key=lambda e: e['created_at'], reverse=True)
    events = events[:limit]
    for e in events:
        e['created_at'] = e['created_at'].isoformat()
    return events