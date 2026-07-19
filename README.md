<<<<<<< HEAD
# SignBridge — Backend

A full-stack accessibility app that bridges sign language and speech in real time.
The frontend runs entirely in the browser (MediaPipe Hands + Web Speech API); this
backend gives it real user accounts, persistent conversation history, a custom sign
vocabulary, and usage analytics.

## Features
- **Auth**: registration, login, logout, session-based auth, rate-limited login/register,
  password strength validation, login-attempt logging (`login_events` table).
- **Translation logging**: every recognized sign and every transcribed voice line is saved
  to the database under a `Conversation`, so history survives a page refresh.
- **Custom gestures**: each user can add their own sign → word mappings on top of the
  6 built-in gestures (Hello, Yes, Wait, Peace, Thank you, I love you).
- **Analytics dashboard**: total translations, sign vs. voice split, most-used signs,
  login count — all computed live from the database.
- **Tests**: 15 pytest tests covering auth and the API (`tests/`), all passing.

## Project structure
```
signbridge/
├── app.py                 # Flask app factory, blueprint registration
├── config.py               # Config + TestConfig
├── database.py               # SQLAlchemy models (User, Conversation, Translation, Gesture, LoginEvent)
├── security.py                # Rate limiter + validators
├── auth.py                     # Register / login / logout / session guard
├── translate_routes.py          # Translation logging + history API
├── gesture_routes.py              # Custom gesture CRUD
├── analytics.py                    # Stats API + page routes
├── templates/                       # Jinja2 pages (login, register, dashboard, history, gestures, analytics)
├── static/
│   ├── css/style.css                  # Shared styling
│   └── js/app.js                       # Camera, MediaPipe hand-sign detection, TTS/STT, API calls
├── tests/                                # pytest suite
└── requirements.txt
```

## Running it locally
```bash
pip install -r requirements.txt
python app.py
```
Then open **http://127.0.0.1:5000** in Chrome, create an account, and click
"Start Camera" (grant camera + mic permission) to try live sign-to-speech and
speech-to-text translation.

## Running the tests
```bash
python -m pytest tests/ -v
```

## Notes for your abstract / demo
- Gesture recognition is landmark-geometry based (counts extended fingers via
  MediaPipe Hands), not a trained neural network — this keeps it fully offline and
  dependency-light, and is easy to explain to judges without needing a big dataset.
- For a real deployment, set `SECRET_KEY` as an environment variable and swap the
  in-memory rate-limiter storage for Redis.
=======
# signbridge
Real-time sign language ↔ speech translator built with Flask, MediaPipe hand tracking, and the Web Speech API — with custom gesture vocab, conversation history, and usage analytics.
>>>>>>> 37a9e79e12fe2f818742b52a42f47a70b7958363
