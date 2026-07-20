from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')  # user | admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    conversations = db.relationship('Conversation', backref='user', lazy=True, cascade='all, delete-orphan')
    gestures = db.relationship('Gesture', backref='owner', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'email': self.email, 'role': self.role}


class Conversation(db.Model):
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(150), default='Conversation')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    translations = db.relationship('Translation', backref='conversation', lazy=True, cascade='all, delete-orphan')


class Translation(db.Model):
    __tablename__ = 'translations'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    source = db.Column(db.String(10), nullable=False)  # sign | voice
    gesture_key = db.Column(db.String(50))
    text = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'gesture_key': self.gesture_key,
            'text': self.text,
            'created_at': self.created_at.isoformat(),
        }


class Gesture(db.Model):
    __tablename__ = 'gestures'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # null = global default
    gesture_key = db.Column(db.String(50), nullable=False)
    word = db.Column(db.String(120), nullable=False)
    emoji = db.Column(db.String(10), default='\U0001f590')
    is_custom = db.Column(db.Boolean, default=False)
    language = db.Column(db.String(10), default='ASL')       # ASL | BSL | ISL
    shape_key = db.Column(db.String(30), nullable=True)       # maps to a camera-detectable hand shape, or NULL
    detectable = db.Column(db.Boolean, default=False)         # True = live camera can recognize this one

    __table_args__ = (db.UniqueConstraint('user_id', 'gesture_key', name='uq_user_gesture'),)

    def to_dict(self):
        return {
            'gesture_key': self.gesture_key,
            'word': self.word,
            'emoji': self.emoji,
            'is_custom': self.is_custom,
            'language': self.language,
            'shape_key': self.shape_key,
            'detectable': self.detectable,
        }


class LoginEvent(db.Model):
    """Security/forensics log of every login attempt, successful or not."""
    __tablename__ = 'login_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    email_attempted = db.Column(db.String(120))
    ip_address = db.Column(db.String(64))
    success = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


SUPPORTED_LANGUAGES = ['ASL', 'BSL', 'ISL']

# The 11 hand shapes classifyGesture() in app.js can actually tell apart via
# MediaPipe landmarks (finger-extension pattern). Every language maps its most
# essential words onto these same 11 shapes so the camera can recognize them live.
CORE_SHAPES = [
    ('FIST',      'Yes',        '\u270a'),
    ('OPEN_HAND', 'Hello',      '\U0001f44b'),
    ('ONE',       'Wait',       '\u261d\ufe0f'),
    ('TWO',       'Peace',      '\u270c\ufe0f'),
    ('THREE',     'Three',      '3\ufe0f\u20e3'),
    ('FOUR',      'Four',       '4\ufe0f\u20e3'),
    ('THUMB',     'Thank you',  '\U0001f44d'),
    ('PINKY',     'Promise',    '\U0001f919'),
    ('ILY',       'I love you', '\U0001f91f'),
    ('ROCK',      'Rock on',    '\U0001f918'),
    ('OK',        'OK',         '\U0001f44c'),
]

# The remaining ~39 words per language: reference vocabulary shown in the
# Supported Signs dropdown for learning, not yet mapped to a detectable shape.
REFERENCE_WORDS = {
    'ASL': [
        ('Good morning', '\u2600\ufe0f'), ('Good afternoon', '\U0001f324\ufe0f'), ('Good evening', '\U0001f306'),
        ('Good night', '\U0001f319'), ('Goodbye', '\U0001f44b'), ('Please', '\U0001f64f'), ('Sorry', '\U0001f614'),
        ('Excuse me', '\U0001f647'), ('Name', '\U0001faaa'), ('Friend', '\U0001f91d'), ('Family', '\U0001f46a'),
        ('Mother', '\U0001f469'), ('Father', '\U0001f468'), ('Sister', '\U0001f467'), ('Brother', '\U0001f466'),
        ('Baby', '\U0001f476'), ('Help', '\U0001f6a8'), ('Stop', '\u270b'), ('Go', '\U0001f6b6'),
        ('Eat', '\U0001f37d\ufe0f'), ('Drink', '\U0001f965'), ('Water', '\U0001f4a7'), ('More', '\u2795'),
        ('Finish', '\u2705'), ('Want', '\U0001f64b'), ('Love', '\u2764\ufe0f'), ('Happy', '\U0001f60a'),
        ('Sad', '\U0001f622'), ('Angry', '\U0001f620'), ('Tired', '\U0001f634'), ('Hot', '\U0001f525'),
        ('Cold', '\u2744\ufe0f'), ('School', '\U0001f3eb'), ('Work', '\U0001f4bc'), ('Home', '\U0001f3e0'),
        ('Bathroom', '\U0001f6bb'), ('Doctor', '\U0001fa7a'), ('Red', '\U0001f534'), ('Blue', '\U0001f535'),
    ],
    'BSL': [
        ('Good morning', '\u2600\ufe0f'), ('Good afternoon', '\U0001f324\ufe0f'), ('Good evening', '\U0001f306'),
        ('Good night', '\U0001f319'), ('Goodbye', '\U0001f44b'), ('Please', '\U0001f64f'), ('Sorry', '\U0001f614'),
        ('Excuse me', '\U0001f647'), ('Name', '\U0001faaa'), ('Friend', '\U0001f91d'), ('Family', '\U0001f46a'),
        ('Mum', '\U0001f469'), ('Dad', '\U0001f468'), ('Sister', '\U0001f467'), ('Brother', '\U0001f466'),
        ('Baby', '\U0001f476'), ('Help', '\U0001f6a8'), ('Stop', '\u270b'), ('Go', '\U0001f6b6'),
        ('Eat', '\U0001f37d\ufe0f'), ('Drink', '\U0001f965'), ('Water', '\U0001f4a7'), ('More', '\u2795'),
        ('Finished', '\u2705'), ('Want', '\U0001f64b'), ('Love', '\u2764\ufe0f'), ('Happy', '\U0001f60a'),
        ('Sad', '\U0001f622'), ('Angry', '\U0001f620'), ('Tired', '\U0001f634'), ('Hot', '\U0001f525'),
        ('Cold', '\u2744\ufe0f'), ('School', '\U0001f3eb'), ('Work', '\U0001f4bc'), ('Home', '\U0001f3e0'),
        ('Toilet', '\U0001f6bb'), ('Doctor', '\U0001fa7a'), ('Red', '\U0001f534'), ('Blue', '\U0001f535'),
    ],
    'ISL': [
        ('Good morning', '\u2600\ufe0f'), ('Good afternoon', '\U0001f324\ufe0f'), ('Good evening', '\U0001f306'),
        ('Good night', '\U0001f319'), ('Goodbye', '\U0001f44b'), ('Please', '\U0001f64f'), ('Sorry', '\U0001f614'),
        ('Excuse me', '\U0001f647'), ('Name', '\U0001faaa'), ('Friend', '\U0001f91d'), ('Family', '\U0001f46a'),
        ('Mother', '\U0001f469'), ('Father', '\U0001f468'), ('Sister', '\U0001f467'), ('Brother', '\U0001f466'),
        ('Baby', '\U0001f476'), ('Help', '\U0001f6a8'), ('Stop', '\u270b'), ('Go', '\U0001f6b6'),
        ('Eat', '\U0001f37d\ufe0f'), ('Drink', '\U0001f965'), ('Water', '\U0001f4a7'), ('More', '\u2795'),
        ('Finish', '\u2705'), ('Want', '\U0001f64b'), ('Love', '\u2764\ufe0f'), ('Happy', '\U0001f60a'),
        ('Sad', '\U0001f622'), ('Angry', '\U0001f620'), ('Tired', '\U0001f634'), ('Hot', '\U0001f525'),
        ('Cold', '\u2744\ufe0f'), ('School', '\U0001f3eb'), ('Work', '\U0001f4bc'), ('Home', '\U0001f3e0'),
        ('Bathroom', '\U0001f6bb'), ('Doctor', '\U0001fa7a'), ('Guest', '\U0001f64c'), ('Respect', '\U0001f64f'),
    ],
}


def _slug(word):
    return word.upper().replace(' ', '_').replace(',', '').replace("'", '')


def _ensure_gesture_columns():
    """Safe, additive-only migration: ADD COLUMN never touches existing data
    or foreign keys, unlike ALTER TABLE RENAME (which is what caused the
    IDon Portal corruption cascade) — so this is fine to run on every boot."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if 'gestures' not in inspector.get_table_names():
        return
    existing_cols = {c['name'] for c in inspector.get_columns('gestures')}
    with db.engine.connect() as conn:
        if 'language' not in existing_cols:
            conn.execute(text("ALTER TABLE gestures ADD COLUMN language VARCHAR(10) DEFAULT 'ASL'"))
        if 'shape_key' not in existing_cols:
            conn.execute(text("ALTER TABLE gestures ADD COLUMN shape_key VARCHAR(30)"))
        if 'detectable' not in existing_cols:
            conn.execute(text("ALTER TABLE gestures ADD COLUMN detectable BOOLEAN DEFAULT 0"))
        conn.commit()


def seed_default_gestures():
    _ensure_gesture_columns()

    # Drop the old pre-language default set (OPEN_HAND/FIST/... with no
    # language tag) so it doesn't show up as a duplicate alongside the new
    # ASL_OPEN_HAND etc. Only touches user_id=None (global defaults), never
    # a learner's own custom gestures.
    legacy_keys = ['OPEN_HAND', 'FIST', 'ONE', 'PEACE', 'THUMB', 'ILY']
    Gesture.query.filter(Gesture.user_id.is_(None), Gesture.gesture_key.in_(legacy_keys)).delete(
        synchronize_session=False
    )

    for lang in SUPPORTED_LANGUAGES:
        for shape_key, word, emoji in CORE_SHAPES:
            key = f'{lang}_{shape_key}'
            exists = Gesture.query.filter_by(gesture_key=key, user_id=None).first()
            if not exists:
                db.session.add(Gesture(
                    gesture_key=key, word=word, emoji=emoji, is_custom=False, user_id=None,
                    language=lang, shape_key=shape_key, detectable=True,
                ))
        for word, emoji in REFERENCE_WORDS.get(lang, []):
            key = f'{lang}_{_slug(word)}'
            exists = Gesture.query.filter_by(gesture_key=key, user_id=None).first()
            if not exists:
                db.session.add(Gesture(
                    gesture_key=key, word=word, emoji=emoji, is_custom=False, user_id=None,
                    language=lang, shape_key=None, detectable=False,
                ))
    db.session.commit()