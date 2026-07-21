"""
Lesson content for the "Learn Sign Language" module.

Design note on `detectable`:
SignBridge's camera recognizer (static/js/app.js `classifyGesture`) is a
landmark-geometry classifier, not a trained model — it currently distinguishes
six hand-shapes (OPEN_HAND, FIST, ONE, PEACE, THUMB, ILY) plus, for practice
mode only, a simple extended-finger count used for the Numbers category
(see static/js/learn.js). Lessons whose sign isn't one those shapes can
represent are marked `detectable: False`: they still open the camera in
"free practice" (no pass/fail scoring, just a mirror-style self-check) so we
never claim recognition accuracy we don't actually have.
"""

CATEGORIES = [
    {"key": "greetings", "label": "Greetings", "icon": "👋",
     "blurb": "The everyday signs you'll use to open and close a conversation."},
    {"key": "numbers", "label": "Numbers", "icon": "🔢",
     "blurb": "Counting 1 through 5, detected live by counting extended fingers."},
    {"key": "alphabet", "label": "Alphabet", "icon": "🔤",
     "blurb": "A starter set of fingerspelled letters for spelling out names and words."},
    {"key": "emergency", "label": "Emergency", "icon": "🚨",
     "blurb": "Critical phrases for urgent situations — paired with Emergency Mode."},
    {"key": "daily", "label": "Daily Conversations", "icon": "💬",
     "blurb": "Common responses for everyday back-and-forth."},
]

DETECTABLE_SHAPES = {"OPEN_HAND", "FIST", "ONE", "PEACE", "THUMB", "ILY"}
NUMBER_SHAPES = {"NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5"}


def _lesson(key, category, gesture_key, word, meaning, description, emoji):
    detectable = gesture_key in DETECTABLE_SHAPES or gesture_key in NUMBER_SHAPES
    return {
        "key": key,
        "category": category,
        "gesture_key": gesture_key,
        "word": word,
        "meaning": meaning,
        "description": description,
        "emoji": emoji,
        "detectable": detectable,
    }


LESSONS = [
    # ---------- Greetings ----------
    _lesson("GREET_HELLO", "greetings", "OPEN_HAND", "Hello",
            "A friendly, open-palm greeting.",
            "Hold your hand up, palm facing out, fingers relaxed and spread. This is the same "
            "open-hand shape SignBridge's live translator already recognizes as \"Hello.\"", "👋"),
    _lesson("GREET_THANKYOU", "greetings", "THUMB", "Thank you",
            "Showing gratitude.",
            "Extend your thumb outward from a loosely closed fist. Hold it steady for about a "
            "second so the camera can lock onto the shape.", "🙏"),
    _lesson("GREET_PEACE", "greetings", "PEACE", "Peace",
            "A peace sign, often used as a warm sign-off.",
            "Extend your index and middle fingers in a V, keeping your ring and pinky fingers "
            "curled down.", "✌️"),
    _lesson("GREET_ILY", "greetings", "ILY", "I love you",
            "The combined I + L + Y handshape, one of the most recognized ASL signs.",
            "Extend your thumb, index finger, and pinky finger, keeping your middle and ring "
            "fingers folded down.", "🤟"),

    # ---------- Numbers (finger-count based, scored in practice mode) ----------
    _lesson("NUM_ONE", "numbers", "NUM_1", "1",
            "The number one.",
            "Extend just your index finger, all other fingers curled down.", "1️⃣"),
    _lesson("NUM_TWO", "numbers", "NUM_2", "2",
            "The number two.",
            "Extend your index and middle fingers together, other fingers curled down.", "2️⃣"),
    _lesson("NUM_THREE", "numbers", "NUM_3", "3",
            "The number three.",
            "Extend your index, middle, and ring fingers, thumb and pinky curled down.", "3️⃣"),
    _lesson("NUM_FOUR", "numbers", "NUM_4", "4",
            "The number four.",
            "Extend index, middle, ring, and pinky fingers, keep your thumb tucked in.", "4️⃣"),
    _lesson("NUM_FIVE", "numbers", "NUM_5", "5",
            "The number five.",
            "Open your whole hand — all five fingers extended and spread.", "5️⃣"),

    # ---------- Alphabet (educational; fingerspelling isn't scored by the geometry classifier) ----------
    _lesson("ALPHA_A", "alphabet", None, "A",
            "Fist with thumb resting alongside the hand.",
            "Make a fist and rest your thumb against the side of your index finger.", "🅰️"),
    _lesson("ALPHA_B", "alphabet", None, "B",
            "Flat hand, thumb folded across the palm.",
            "Hold your four fingers straight up together and fold your thumb across your palm.", "🅱️"),
    _lesson("ALPHA_L", "alphabet", None, "L",
            "Thumb and index finger form an L shape.",
            "Extend your thumb and index finger at a right angle, other fingers curled down.", "🇱"),
    _lesson("ALPHA_Y", "alphabet", None, "Y",
            "\"Hang loose\" handshape.",
            "Extend your thumb and pinky finger, curl the other three fingers down.", "🇾"),

    # ---------- Emergency (paired with Emergency Mode; educational, free-practice only) ----------
    _lesson("EMG_HELP", "emergency", None, "I need help",
            "Signals that you need immediate assistance.",
            "Place a flat hand under your other fist and lift both upward together.", "🆘"),
    _lesson("EMG_DEAF", "emergency", None, "I am Deaf",
            "Identifies yourself as a Deaf person to first responders or strangers.",
            "Point to your ear, then to yourself, or fingerspell D-E-A-F if unsure.", "🧏"),
    _lesson("EMG_DOCTOR", "emergency", None, "Doctor",
            "Requesting or referring to medical help.",
            "Tap the wrist of a bent middle finger onto the opposite wrist.", "🩺"),
    _lesson("EMG_SLOWLY", "emergency", None, "Please speak slowly",
            "Asks a hearing person to slow down so you can lip-read or follow along.",
            "Flat hand moving slowly forward from your mouth, palm up.", "🐢"),

    # ---------- Daily Conversations ----------
    _lesson("DAILY_YES", "daily", "FIST", "Yes",
            "A nodding fist used to affirm.",
            "Make a fist and bob it up and down slightly, like a nodding head. SignBridge's "
            "live translator already recognizes this shape as \"Yes.\"", "✊"),
    _lesson("DAILY_WAIT", "daily", "ONE", "Wait, one moment",
            "Asking someone to pause briefly.",
            "Extend just your index finger and hold it steady, other fingers curled down.", "☝️"),
    _lesson("DAILY_WATER", "daily", None, "Water",
            "Asking for or referring to water.",
            "Tap a \"W\" handshape (index, middle, ring fingers extended) against your chin.", "💧"),
    _lesson("DAILY_FRIEND", "daily", None, "Friend",
            "Referring to a friend.",
            "Hook your index fingers together, then flip and hook them the other way.", "🧑‍🤝‍🧑"),
]


def lessons_by_category():
    grouped = {c["key"]: [] for c in CATEGORIES}
    for lesson in LESSONS:
        grouped[lesson["category"]].append(lesson)
    return grouped


def get_lesson(key):
    for lesson in LESSONS:
        if lesson["key"] == key:
            return lesson
    return None