"""
AI Sentence Prediction & Auto-Completion engine.

Design note: rather than bolting on a heavyweight language-model dependency
(which would need GPU/API access this project doesn't otherwise require),
this is an extensible **template + context-matching** engine — the kind of
approach real accessibility products use for exactly this "quick reply"
problem, because it's fast, fully offline-capable, and 100% explainable.

It's intentionally structured so a real LLM/NLP model could be swapped in
later behind the same `predict_from_gesture_sequence` / `predict_reply`
functions without touching any call sites.
"""
import re

# ---------- Gesture / word -> sentence completions ----------
# Keyed by the *last* recognized word (case-insensitive). Ranked by confidence (0-1).
GESTURE_COMPLETIONS = {
    "hello": [
        ("Hello!", 0.95),
        ("Hello, how are you?", 0.88),
        ("Hello, nice to meet you.", 0.8),
    ],
    "thank you": [
        ("Thank you!", 0.95),
        ("Thank you so much.", 0.85),
        ("Thank you for your help.", 0.78),
    ],
    "yes": [
        ("Yes.", 0.9),
        ("Yes, that's right.", 0.8),
        ("Yes, please.", 0.75),
    ],
    "wait, one moment": [
        ("One moment, please.", 0.9),
        ("Please wait a second.", 0.8),
        ("Give me a moment.", 0.75),
    ],
    "peace": [
        ("Peace!", 0.85),
        ("Take care.", 0.75),
        ("See you later.", 0.7),
    ],
    "i love you": [
        ("I love you.", 0.95),
        ("I love you too.", 0.85),
    ],
    "water": [
        ("I want water.", 0.9),
        ("Can I have some water?", 0.85),
        ("I need a glass of water.", 0.78),
    ],
    "doctor": [
        ("I need a doctor.", 0.92),
        ("Please call a doctor.", 0.85),
        ("Where is the nearest doctor?", 0.7),
    ],
    "friend": [
        ("This is my friend.", 0.85),
        ("I'm meeting a friend.", 0.75),
    ],
}

# Two- and three-word sequences (order-sensitive, matched against the tail of the
# recognized-word history) map onto more specific completions than any single word.
SEQUENCE_COMPLETIONS = [
    (["i", "want", "water"], [
        ("I want water.", 0.95),
        ("I want a glass of water.", 0.87),
        ("Can I have some water?", 0.8),
    ]),
    (["i", "need", "help"], [
        ("I need help.", 0.96),
        ("I need help right now.", 0.85),
        ("Can someone help me?", 0.8),
    ]),
    (["i", "am", "deaf"], [
        ("I am Deaf.", 0.95),
        ("I am Deaf — please write it down.", 0.75),
    ]),
]

# ---------- Quick-reply chips for common things a hearing person says ----------
# Matched by keyword/phrase against the incoming speech-to-text transcript.
REPLY_PATTERNS = [
    (re.compile(r"\bwhere are you going\b", re.I), [
        ("I'm going home.", 0.9),
        ("I'm going to college.", 0.82),
        ("I'm going to work.", 0.8),
        ("I'm not sure yet.", 0.6),
    ]),
    (re.compile(r"\bhow are you\b", re.I), [
        ("I'm doing well, thank you.", 0.9),
        ("I'm okay.", 0.75),
        ("Not great, to be honest.", 0.55),
    ]),
    (re.compile(r"\bwhat('?s| is) your name\b", re.I), [
        ("My name is...", 0.85),
        ("Nice to meet you.", 0.6),
    ]),
    (re.compile(r"\bdo you need help\b", re.I), [
        ("Yes, please.", 0.9),
        ("No, I'm okay, thank you.", 0.85),
    ]),
    (re.compile(r"\bare you (ok|okay|alright)\b", re.I), [
        ("Yes, I'm okay.", 0.9),
        ("No, I need help.", 0.75),
    ]),
]

GENERIC_REPLIES = [
    ("Yes.", 0.4), ("No.", 0.4), ("Can you repeat that?", 0.35), ("Thank you.", 0.3),
]


def _norm(word):
    return (word or "").strip().lower()


def predict_from_gesture_sequence(history, limit=3):
    """
    history: list of recognized words/phrases in order (most recent last), e.g.
             ["I", "Want", "Water"] or ["Hello"].
    Returns ranked [{text, confidence}], most confident first.
    """
    if not history:
        return []
    tail_words = [_norm(w) for w in history[-3:]]

    # Prefer the longest matching sequence first (most specific / most context).
    for seq, completions in sorted(SEQUENCE_COMPLETIONS, key=lambda s: -len(s[0])):
        n = len(seq)
        if n <= len(tail_words) and tail_words[-n:] == seq:
            return _rank(completions, limit)

    last = _norm(history[-1])
    if last in GESTURE_COMPLETIONS:
        return _rank(GESTURE_COMPLETIONS[last], limit)

    return []


def predict_reply(transcript, limit=4):
    """transcript: what the hearing person just said (speech-to-text). Returns quick-reply chips."""
    if not transcript:
        return []
    for pattern, completions in REPLY_PATTERNS:
        if pattern.search(transcript):
            return _rank(completions, limit)
    # No specific pattern matched — fall back to generic low-confidence replies
    # rather than showing nothing, since "smart" here still means "useful default".
    return _rank(GENERIC_REPLIES, limit)


def _rank(completions, limit):
    ranked = sorted(completions, key=lambda c: -c[1])[:limit]
    return [{"text": text, "confidence": round(conf * 100)} for text, conf in ranked]