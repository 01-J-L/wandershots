from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from flask_apscheduler import APScheduler


db = SQLAlchemy()
DB_NAME = "database.db"

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'dev_key_change_this_in_prod'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'
    
    # --- SCHEDULER SETUP ---
    scheduler = APScheduler()

    # This task runs every 1 hour to check for events happening tomorrow
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

    from .models import User, ContactMessage, Booking

    create_database(app)

    # CREATE DEFAULT ADMIN/SUPERADMIN
    with app.app_context():
        create_admin_user()

    login_manager = LoginManager()
    login_manager.login_view = 'auth.admin_login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    # Start the background task scheduler
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
    # Check if default superadmin exists
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