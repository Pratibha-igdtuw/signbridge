from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for

from database import db, User, LoginEvent
from security import limiter, is_valid_email, is_strong_password

auth_bp = Blueprint('auth', __name__)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return wrapper


def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None


# ---------- Pages ----------

@auth_bp.route('/login', methods=['GET'])
def login_page():
    if current_user():
        return redirect(url_for('analytics.dashboard_page'))
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET'])
def register_page():
    if current_user():
        return redirect(url_for('analytics.dashboard_page'))
    return render_template('register.html')


# ---------- API ----------

@auth_bp.route('/api/auth/register', methods=['POST'])
@limiter.limit('10 per hour')
def register():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not is_valid_email(email):
        return jsonify({'error': 'Please provide a valid email address'}), 400
    ok, msg = is_strong_password(password)
    if not ok:
        return jsonify({'error': msg}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 409

    user = User(name=name, email=email, role='user')
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    return jsonify({'message': 'Account created', 'user': user.to_dict()}), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
@limiter.limit('10 per minute')
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    ip = request.remote_addr

    user = User.query.filter_by(email=email).first()
    success = bool(user and user.check_password(password))

    db.session.add(LoginEvent(
        user_id=user.id if user else None,
        email_attempted=email,
        ip_address=ip,
        success=success,
    ))
    db.session.commit()

    if not success:
        return jsonify({'error': 'Invalid email or password'}), 401

    user.last_login = datetime.utcnow()
    db.session.commit()
    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    return jsonify({'message': 'Logged in', 'user': user.to_dict()})


@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})


@auth_bp.route('/api/auth/me', methods=['GET'])
def me():
    user = current_user()
    return jsonify({'user': user.to_dict() if user else None})


@auth_bp.route('/api/auth/login-history', methods=['GET'])
@login_required
def login_history():
    user = current_user()
    events = (
        LoginEvent.query.filter_by(user_id=user.id)
        .order_by(LoginEvent.id.desc())
        .limit(25)
        .all()
    )
    return jsonify([
        {
            'ip_address': e.ip_address,
            'success': e.success,
            'created_at': e.created_at.isoformat(),
        }
        for e in events
    ])
