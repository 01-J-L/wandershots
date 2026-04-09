from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from flask_apscheduler import APScheduler
from authlib.integrations.flask_client import OAuth # NEW OAUTH IMPORT
from werkzeug.middleware.proxy_fix import ProxyFix

db = SQLAlchemy()
DB_NAME = "database.db"
oauth = OAuth() # INITIALIZE OAUTH

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'super_secret_key_for_dev_only_123abcXYZ'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'

    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 # 500 MB limit for file uploads

    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # --- OAUTH CREDENTIALS (REPLACE WITH YOUR ACTUAL KEYS) ---
    app.config['GOOGLE_CLIENT_ID'] = "319080976394-p1pj2tkq13bnvja1i3n1ppqfd2hhdfi9.apps.googleusercontent.com"
    app.config['GOOGLE_CLIENT_SECRET'] = "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"  
    app.config['FACEBOOK_CLIENT_ID'] = 1243596504561774
    app.config['FACEBOOK_CLIENT_SECRET'] = 'd4a76979ba15fbb3aad5fa482496b632'
    
    # Initialize OAuth
    oauth.init_app(app)
    
    # Register Google
    oauth.register(
        name='google',
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )
    
    # Register Facebook
    oauth.register(
        name='facebook',
        api_base_url='https://graph.facebook.com/v19.0/',
        access_token_url='https://graph.facebook.com/v19.0/oauth/access_token',
        authorize_url='https://www.facebook.com/v19.0/dialog/oauth',
        client_kwargs={'scope': 'email public_profile'},
        userinfo_endpoint='me?fields=id,name,email'
    )
    # ---------------------------------------------------------
    
    scheduler = APScheduler()

    @scheduler.task('interval', id='event_reminders', hours=1)
    def scheduled_reminders():
        with app.app_context():
            from .views import check_upcoming_events
            check_upcoming_events(app)
    
    db.init_app(app)

    from .views import views
    from .auth import auth

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')

    from .models import User, ContactMessage, Booking, BlockedDate

    create_database(app)

    with app.app_context():
        create_admin_user()

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    scheduler.api_enabled = True
    scheduler.init_app(app)
    scheduler.start()

    return app

def create_database(app):
    if not path.exists('website/' + DB_NAME):
        with app.app_context():
            db.create_all()
        print('Created Database!')

def create_admin_user():
    from .models import User
    admin = User.query.filter_by(username="superadmin").first()
    if not admin:
        print("Creating Default Super Admin Account...")
        new_admin = User(
            username="superadmin",
            first_name="Super Admin",
            role="super_admin",
            password=generate_password_hash("admin123", method='scrypt')
        )
        db.session.add(new_admin)
        db.session.commit()
        print("Super Admin Created: superadmin / admin123")