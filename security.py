import re

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def is_valid_email(email):
    return bool(EMAIL_RE.match(email or ''))


def is_strong_password(password):
    if not password or len(password) < 8:
        return False, 'Password must be at least 8 characters long.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must include at least one uppercase letter.'
    if not re.search(r'[0-9]', password):
        return False, 'Password must include at least one number.'
    return True, ''
