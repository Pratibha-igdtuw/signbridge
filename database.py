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
    # 'chat' (default/legacy For You transcript), 'live' (Live Conversation screen),
    # or 'emergency' (Emergency Mode session). Nullable for backward compatibility with
    # rows created before this column existed — treat NULL as 'chat'.
    mode = db.Column(db.String(20), default='chat')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    translations = db.relationship('Translation', backref='conversation', lazy=True, cascade='all, delete-orphan')


class Translation(db.Model):
    __tablename__ = 'translations'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    source = db.Column(db.String(10), nullable=False)  # sign | voice | text
    gesture_key = db.Column(db.String(50))
    text = db.Column(db.String(500), nullable=False)
    language = db.Column(db.String(10), default='ASL')  # ASL, BSL, ISL
    # Who "said" it in a two-way Live Conversation: 'hearing' or 'deaf'. Nullable/unused
    # for ordinary For You transcript rows.
    sender = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'gesture_key': self.gesture_key,
            'text': self.text,
            'language': self.language,
            'sender': self.sender,
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
    language = db.Column(db.String(10), default='ASL', nullable=False)  # ASL, BSL, ISL

    __table_args__ = (db.UniqueConstraint('user_id', 'gesture_key', 'language', name='uq_user_gesture_lang'),)

    def to_dict(self):
        return {
            'gesture_key': self.gesture_key,
            'word': self.word,
            'emoji': self.emoji,
            'is_custom': self.is_custom,
            'language': self.language,
        }


class PracticeAttempt(db.Model):
    """One attempt at a Learn-module lesson (Practice Now / Practice Mode)."""
    __tablename__ = 'practice_attempts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    lesson_key = db.Column(db.String(50), nullable=False)
    expected_gesture = db.Column(db.String(50))
    detected_gesture = db.Column(db.String(50))
    confidence = db.Column(db.Float)  # 0-100, from the client-side detector
    # NULL = "unscored" free-practice attempt (lesson has no detectable shape yet).
    # True/False = a real pass/fail comparison against the expected gesture.
    correct = db.Column(db.Boolean)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('practice_attempts', lazy=True, cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'lesson_key': self.lesson_key,
            'expected_gesture': self.expected_gesture,
            'detected_gesture': self.detected_gesture,
            'confidence': self.confidence,
            'correct': self.correct,
            'created_at': self.created_at.isoformat(),
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


# ASL: American Sign Language (50 gestures)
ASL_GESTURES = [
    # Greetings & Basic (5)
    ('HELLO', 'Hello', '\U0001f44b', 'ASL'),
    ('GOODBYE', 'Goodbye', '\U0001f44b', 'ASL'),
    ('NICE_MEET', 'Nice to meet you', '\U0001f91d', 'ASL'),
    ('HOW_ARE_YOU', 'How are you?', '\U0001f937', 'ASL'),
    ('GOOD', 'Good', '\U0001f44d', 'ASL'),
    # Numbers 0-9 (10)
    ('ZERO', 'Zero', '0', 'ASL'),
    ('ONE', 'One', '1', 'ASL'),
    ('TWO', 'Two', '2', 'ASL'),
    ('THREE', 'Three', '3', 'ASL'),
    ('FOUR', 'Four', '4', 'ASL'),
    ('FIVE', 'Five', '5', 'ASL'),
    ('SIX', 'Six', '6', 'ASL'),
    ('SEVEN', 'Seven', '7', 'ASL'),
    ('EIGHT', 'Eight', '8', 'ASL'),
    ('NINE', 'Nine', '9', 'ASL'),
    # Emotions (8)
    ('HAPPY', 'Happy', '\U0001f60a', 'ASL'),
    ('SAD', 'Sad', '\U0001f622', 'ASL'),
    ('ANGRY', 'Angry', '\U0001f60c', 'ASL'),
    ('EXCITED', 'Excited', '\U0001f929', 'ASL'),
    ('TIRED', 'Tired', '\U0001f62a', 'ASL'),
    ('LOVE', 'Love', '\u2764\ufe0f', 'ASL'),
    ('SCARED', 'Scared', '\U0001f628', 'ASL'),
    ('CONFUSED', 'Confused', '\U0001f615', 'ASL'),
    # Common Words (15)
    ('PLEASE', 'Please', '\U0001f64f', 'ASL'),
    ('THANK_YOU', 'Thank you', '\U0001f44f', 'ASL'),
    ('YES', 'Yes', '\u270a', 'ASL'),
    ('NO', 'No', '\u274c', 'ASL'),
    ('WAIT', 'Wait', '\u270b', 'ASL'),
    ('STOP', 'Stop', '\U0001f6d1', 'ASL'),
    ('HELP', 'Help', '\U0001f198', 'ASL'),
    ('WATER', 'Water', '\U0001f4a7', 'ASL'),
    ('FOOD', 'Food', '\U0001f37d', 'ASL'),
    ('SLEEP', 'Sleep', '\U0001f62a', 'ASL'),
    ('WORK', 'Work', '\U0001f4bc', 'ASL'),
    ('SCHOOL', 'School', '\U0001f3eb', 'ASL'),
    ('DOCTOR', 'Doctor', '\u2695', 'ASL'),
    ('MOTHER', 'Mother', '\U0001f469', 'ASL'),
    ('FATHER', 'Father', '\U0001f468', 'ASL'),
    # Advanced (12)
    ('MONEY', 'Money', '\U0001f4b0', 'ASL'),
    ('TIME', 'Time', '\u23f0', 'ASL'),
    ('PERSON', 'Person', '\U0001f64b', 'ASL'),
    ('HOUSE', 'House', '\U0001f3e0', 'ASL'),
    ('CAR', 'Car', '\U0001f697', 'ASL'),
    ('COMPUTER', 'Computer', '\U0001f4bb', 'ASL'),
    ('PHONE', 'Phone', '\U0001f4f1', 'ASL'),
    ('BOOK', 'Book', '\U0001f4d6', 'ASL'),
    ('UNDERSTAND', 'I understand', '\U0001f9e0', 'ASL'),
    ('LEARN', 'Learn', '\U0001f4da', 'ASL'),
    ('SHOW', 'Show me', '\U0001f440', 'ASL'),
    ('NAME', 'What is your name?', '\U0001f524', 'ASL'),
]

# BSL: British Sign Language (50 gestures)
BSL_GESTURES = [
    # Greetings & Basic (5)
    ('HELLO', 'Hello', '\U0001f44b', 'BSL'),
    ('CHEERS', 'Cheers', '\U0001f37b', 'BSL'),
    ('HOW_DO', 'How do you do?', '\U0001f91d', 'BSL'),
    ('ALRIGHT', 'Alright?', '\U0001f44d', 'BSL'),
    ('GOOD', 'Good', '\U0001f44c', 'BSL'),
    # Numbers 0-9 (10)
    ('ZERO', 'Zero', '0', 'BSL'),
    ('ONE', 'One', '1', 'BSL'),
    ('TWO', 'Two', '2', 'BSL'),
    ('THREE', 'Three', '3', 'BSL'),
    ('FOUR', 'Four', '4', 'BSL'),
    ('FIVE', 'Five', '5', 'BSL'),
    ('SIX', 'Six', '6', 'BSL'),
    ('SEVEN', 'Seven', '7', 'BSL'),
    ('EIGHT', 'Eight', '8', 'BSL'),
    ('NINE', 'Nine', '9', 'BSL'),
    # Emotions (8)
    ('HAPPY', 'Happy', '\U0001f60a', 'BSL'),
    ('UNHAPPY', 'Unhappy', '\U0001f61e', 'BSL'),
    ('CROSS', 'Cross', '\U0001f624', 'BSL'),
    ('DELIGHTED', 'Delighted', '\U0001f917', 'BSL'),
    ('POORLY', 'Poorly', '\U0001f912', 'BSL'),
    ('LOVELY', 'Lovely', '\U0001f495', 'BSL'),
    ('FEAR', 'Fear', '\U0001f631', 'BSL'),
    ('PUZZLED', 'Puzzled', '\U0001f914', 'BSL'),
    # Common Words (15)
    ('PLEASE', 'Please', '\U0001f64f', 'BSL'),
    ('THANK', 'Thank you', '\U0001f44f', 'BSL'),
    ('YES', 'Yes', '\u270a', 'BSL'),
    ('NO', 'No', '\u274c', 'BSL'),
    ('WAIT', 'Wait a minute', '\u23f0', 'BSL'),
    ('FINISH', 'Finish', '\U0001f3c1', 'BSL'),
    ('WANT', 'Do you want?', '\U0001f64b', 'BSL'),
    ('DRINK', 'Drink', '\U0001f95b', 'BSL'),
    ('EAT', 'Eat', '\U0001f37d', 'BSL'),
    ('REST', 'Rest', '\U0001f6cb', 'BSL'),
    ('JOB', 'Job', '\U0001f454', 'BSL'),
    ('COLLEGE', 'College', '\U0001f393', 'BSL'),
    ('HOSPITAL', 'Hospital', '\U0001f3e5', 'BSL'),
    ('MUM', 'Mum', '\U0001f469', 'BSL'),
    ('DAD', 'Dad', '\U0001f468', 'BSL'),
    # Advanced (12)
    ('PAY', 'Pay', '\U0001f4b3', 'BSL'),
    ('CLOCK', 'Clock', '\U0001f550', 'BSL'),
    ('MAN', 'Man', '\U0001f468', 'BSL'),
    ('FLAT', 'Flat', '\U0001f3d8', 'BSL'),
    ('TAXI', 'Taxi', '\U0001f695', 'BSL'),
    ('LAPTOP', 'Laptop', '\U0001f4bb', 'BSL'),
    ('MOBILE', 'Mobile', '\U0001f4f1', 'BSL'),
    ('NEWSPAPER', 'Newspaper', '\U0001f4f0', 'BSL'),
    ('KNOW', 'I know', '\u2728', 'BSL'),
    ('TRAIN', 'Train', '\U0001f682', 'BSL'),
    ('LOOK', 'Look', '\U0001f441', 'BSL'),
    ('TELL', 'Tell me', '\U0001f4ac', 'BSL'),
]

# ISL: Indian Sign Language (50 gestures)
ISL_GESTURES = [
    # Greetings & Basic (5)
    ('NAMASTE', 'Namaste', '\U0001f64f', 'ISL'),
    ('HELLO', 'Hello', '\U0001f44b', 'ISL'),
    ('SWAGAT', 'Welcome', '\U0001f917', 'ISL'),
    ('AAPKA_SWAAGAT', 'Your welcome', '\U0001f44f', 'ISL'),
    ('THEEK', 'Okay', '\u2705', 'ISL'),
    # Numbers 0-9 (10)
    ('ZERO', 'Zero', '0', 'ISL'),
    ('EK', 'One', '1', 'ISL'),
    ('DO', 'Two', '2', 'ISL'),
    ('TEEN', 'Three', '3', 'ISL'),
    ('CHAR', 'Four', '4', 'ISL'),
    ('PAANCH', 'Five', '5', 'ISL'),
    ('CHEH', 'Six', '6', 'ISL'),
    ('SAAT', 'Seven', '7', 'ISL'),
    ('AATH', 'Eight', '8', 'ISL'),
    ('NAU', 'Nine', '9', 'ISL'),
    # Emotions (8)
    ('KHUSHI', 'Happy', '\U0001f60a', 'ISL'),
    ('DUKH', 'Sad', '\U0001f622', 'ISL'),
    ('GUSSA', 'Anger', '\U0001f60c', 'ISL'),
    ('KHUSHNUMA', 'Excited', '\U0001f929', 'ISL'),
    ('THAKAVAT', 'Tired', '\U0001f62a', 'ISL'),
    ('PYAR', 'Love', '\u2764\ufe0f', 'ISL'),
    ('DARR', 'Fear', '\U0001f628', 'ISL'),
    ('PARESHANI', 'Worry', '\U0001f630', 'ISL'),
    # Common Words (15)
    ('KRIPA', 'Please', '\U0001f64f', 'ISL'),
    ('SHUKRIYA', 'Thank you', '\U0001f64f', 'ISL'),
    ('HAA', 'Yes', '\u270a', 'ISL'),
    ('NAHIN', 'No', '\u274c', 'ISL'),
    ('RUKHO', 'Wait', '\u270b', 'ISL'),
    ('BANDH', 'Close/Stop', '\U0001f6d1', 'ISL'),
    ('MADAD', 'Help', '\U0001f198', 'ISL'),
    ('PANI', 'Water', '\U0001f4a7', 'ISL'),
    ('KHANA', 'Food', '\U0001f37d', 'ISL'),
    ('NEEND', 'Sleep', '\U0001f62a', 'ISL'),
    ('KAM', 'Work', '\U0001f4bc', 'ISL'),
    ('VIDYALAYA', 'School', '\U0001f3eb', 'ISL'),
    ('VAIDYA', 'Doctor', '\u2695', 'ISL'),
    ('MATA', 'Mother', '\U0001f469', 'ISL'),
    ('PITA', 'Father', '\U0001f468', 'ISL'),
    # Advanced (12)
    ('PAISA', 'Money', '\U0001f4b0', 'ISL'),
    ('SAMAY', 'Time', '\u23f0', 'ISL'),
    ('VYAKTI', 'Person', '\U0001f64b', 'ISL'),
    ('GHAR', 'House', '\U0001f3e0', 'ISL'),
    ('GAADI', 'Car', '\U0001f697', 'ISL'),
    ('KOMPYOOTAR', 'Computer', '\U0001f4bb', 'ISL'),
    ('PHONE', 'Phone', '\U0001f4f1', 'ISL'),
    ('KITAAB', 'Book', '\U0001f4d6', 'ISL'),
    ('SAMAJH', 'I understand', '\U0001f9e0', 'ISL'),
    ('SIKHNA', 'Learn', '\U0001f4da', 'ISL'),
    ('DIKHANA', 'Show me', '\U0001f440', 'ISL'),
    ('NAAM', 'Name', '\U0001f524', 'ISL'),
]

DEFAULT_GESTURES = ASL_GESTURES + BSL_GESTURES + ISL_GESTURES


def run_light_migrations():
    """
    db.create_all() only creates tables that don't exist yet — it never alters an
    existing table. Since this project ships a pre-populated signbridge.db, adding a
    nullable column to Conversation/Translation needs an explicit ALTER TABLE the
    first time the app boots against an older database file. Safe to call on every
    startup: it no-ops once the columns are present.
    """
    inspector = db.inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    def add_column_if_missing(table, column, ddl_type):
        if table not in existing_tables:
            return
        cols = {c['name'] for c in inspector.get_columns(table)}
        if column not in cols:
            with db.engine.begin() as conn:
                conn.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}')

    add_column_if_missing('conversations', 'mode', "VARCHAR(20) DEFAULT 'chat'")
    add_column_if_missing('translations', 'sender', 'VARCHAR(10)')


def seed_default_gestures():
    for key, word, emoji, language in DEFAULT_GESTURES:
        exists = Gesture.query.filter_by(gesture_key=key, user_id=None, language=language).first()
        if not exists:
            db.session.add(Gesture(gesture_key=key, word=word, emoji=emoji, is_custom=False, user_id=None, language=language))
    db.session.commit()