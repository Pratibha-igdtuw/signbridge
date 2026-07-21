# SignBridge — Backend

A full-stack accessibility app that bridges sign language and speech in real time.
The frontend runs entirely in the browser (MediaPipe Hands + Web Speech API); this
backend gives it real user accounts, persistent conversation history, a custom sign
vocabulary, usage analytics, guided lessons, an emergency communication mode, and a
live two-way conversation screen.

## Features
- **Auth**: registration, login, logout, session-based auth, rate-limited login/register,
  password strength validation, login-attempt logging (`login_events` table).
- **Translation logging**: every recognized sign, transcribed voice line, and typed message
  is saved to the database under a `Conversation`, so history survives a page refresh.
- **Custom gestures**: each user can add their own sign → word mappings on top of the
  6 built-in gestures (Hello, Yes, Wait, Peace, Thank you, I love you).
- **Learn & Practice Mode**: structured lessons across Greetings, Numbers, Alphabet,
  Emergency, and Daily Conversations, with live camera scoring for gestures the geometry
  classifier can actually recognize, and a progress dashboard (streak, accuracy, sessions).
- **Emergency Mode**: a high-contrast, large-font, one-screen interface with quick
  communication buttons (text-to-speech), plus speech→text and sign→text, all logged
  separately from ordinary conversation history.
- **Live Conversation**: a two-way, messaging-style screen — the hearing person's speech/text
  becomes a bubble, the Deaf user replies by signing or typing and it's read aloud — with
  clear, export, and auto-scroll.
- **Analytics dashboard**: total translations, sign vs. voice split, most-used signs, weekly
  activity chart, practice accuracy/streak, top learning categories, recent activity feed,
  and an approximate average session length — all computed live from the database.
- **Tests**: 29 pytest tests covering auth, the core API, and the new Learn/Emergency/Live
  features (`tests/`), all passing.

## Project structure
```
signbridge/
├── app.py                    # Flask app factory, blueprint registration, schema migration
├── config.py                  # Config + TestConfig
├── database.py                  # SQLAlchemy models (User, Conversation, Translation,
│                                   Gesture, PracticeAttempt, LoginEvent) + light migrations
├── security.py                    # Rate limiter + validators
├── auth.py                          # Register / login / logout / session guard
├── translate_routes.py                # Translation logging + history API (For You page)
├── gesture_routes.py                    # Custom gesture CRUD
├── learn_content.py                       # Static lesson data for the Learn module
├── learn_routes.py                          # Lesson pages + practice attempt/progress API
├── emergency_routes.py                        # Emergency Mode page + logging API
├── live_routes.py                               # Live Conversation page + send/list/export API
├── progress_utils.py                              # Shared streak/accuracy/timeline helpers
├── analytics.py                                     # Stats API + page routes
├── templates/                                         # Jinja2 pages
├── static/
│   ├── css/style.css, home.css                          # Shared styling
│   └── js/app.js, practice.js, emergency.js, live.js        # Camera/MediaPipe, TTS/STT, API calls
├── tests/                                                      # pytest suite
└── requirements.txt
```

## Running it locally
```bash
pip install -r requirements.txt
python app.py
```
Then open **http://127.0.0.1:5000** in Chrome, create an account, and try:
- **For You** — live sign-to-speech and speech-to-text translation
- **Learn** — pick a lesson and hit "Practice Now" to try camera-scored practice
- **Live Conversation** — a two-way messaging screen for a hearing + Deaf pair
- **🚨 Emergency** (top-right of the nav) — high-contrast quick phrases

## Running the tests
```bash
python -m pytest tests/ -v
```

## Database changes
Existing installs upgrade automatically: `app.py` calls `run_light_migrations()` on startup,
which adds the `conversations.mode` and `translations.sender` columns (used to separate
ordinary chat, Emergency, and Live Conversation history) via `ALTER TABLE` if they're missing,
and creates the new `practice_attempts` table. No existing data is dropped or modified.

## Notes for your abstract / demo
- Gesture recognition is landmark-geometry based (measures finger-extension ratios via
  MediaPipe Hands), not a trained neural network — this keeps it fully offline and
  dependency-light, and is easy to explain to judges without needing a big dataset.
- Practice Mode confidence scores and Smart Recognition Feedback (hand visibility, lighting,
  distance) are derived from that same real geometry/pixel data, not simulated — lessons whose
  sign isn't one of the classifier's recognizable shapes are clearly marked as free practice
  (no camera scoring) rather than faking a score.
- For a real deployment, set `SECRET_KEY` as an environment variable and swap the
  in-memory rate-limiter storage for Redis.