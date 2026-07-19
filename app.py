from flask import Flask, render_template, redirect, url_for
from flask_cors import CORS

from config import Config
from database import db, seed_default_gestures
from security import limiter
from auth import auth_bp, current_user
from translate_routes import translate_bp
from gesture_routes import gesture_bp
from analytics import analytics_bp


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)
    limiter.init_app(app)
    CORS(app, supports_credentials=True)

    app.register_blueprint(auth_bp)
    app.register_blueprint(translate_bp)
    app.register_blueprint(gesture_bp)
    app.register_blueprint(analytics_bp)

    @app.route('/')
    def index():
        if current_user():
            return redirect(url_for('analytics.dashboard_page'))
        return render_template('landing.html')

    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html', message='Page not found'), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template('error.html', message='Too many attempts. Please slow down and try again shortly.'), 429

    with app.app_context():
        db.create_all()
        seed_default_gestures()

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
