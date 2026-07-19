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

    __table_args__ = (db.UniqueConstraint('user_id', 'gesture_key', name='uq_user_gesture'),)

    def to_dict(self):
        return {
            'gesture_key': self.gesture_key,
            'word': self.word,
            'emoji': self.emoji,
            'is_custom': self.is_custom,
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


DEFAULT_GESTURES = [
    ('OPEN_HAND', 'Hello', '\U0001f44b'),
    ('FIST', 'Yes', '\u270a'),
    ('ONE', 'Wait, one moment', '\u261d\ufe0f'),
    ('PEACE', 'Peace', '\u270c\ufe0f'),
    ('THUMB', 'Thank you', '\U0001f44d'),
    ('ILY', 'I love you', '\U0001f91f'),
]


def seed_default_gestures():
    for key, word, emoji in DEFAULT_GESTURES:
        exists = Gesture.query.filter_by(gesture_key=key, user_id=None).first()
        if not exists:
            db.session.add(Gesture(gesture_key=key, word=word, emoji=emoji, is_custom=False, user_id=None))
    db.session.commit()
