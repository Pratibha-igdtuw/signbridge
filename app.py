from flask import Flask, render_template, redirect, url_for, send_from_directory
from flask_cors import CORS
import os

from config import Config
from database import db, seed_default_gestures, run_light_migrations
from security import limiter
from auth import auth_bp, current_user
from translate_routes import translate_bp
from gesture_routes import gesture_bp
from analytics import analytics_bp
from learn_routes import learn_bp
from emergency_routes import emergency_bp
from live_routes import live_bp
from predict_routes import predict_bp
from sync_routes import sync_bp
from isl_predict_routes import isl_predict_bp


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
    app.register_blueprint(learn_bp)
    app.register_blueprint(emergency_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(sync_bp)
    app.register_blueprint(isl_predict_bp)

    @app.context_processor
    def inject_nav_user():
        # Display-only: makes the logged-in user's name available to the
        # navbar (avatar initial + dropdown label). Does not affect routing,
        # auth, or any existing behavior.
        return dict(nav_user=current_user())

    @app.route('/')
    def index():
        if current_user():
            return redirect(url_for('analytics.dashboard_page'))
        return render_template('landing.html')

    @app.route('/sw.js')
    def service_worker():
        # Served at root (not /static/sw.js) so its default scope covers the whole
        # site — a service worker registered from /static/ can only control /static/.
        resp = send_from_directory(os.path.join(app.static_folder, 'js'), 'sw.js')
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html', message='Page not found'), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template('error.html', message='Too many attempts. Please slow down and try again shortly.'), 429

    with app.app_context():
        db.create_all()
        run_light_migrations()
        seed_default_gestures()

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)