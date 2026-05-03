
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from flask_apscheduler import APScheduler
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

# NEW: Import load_dotenv
from dotenv import load_dotenv

# NEW: Import datetime
from datetime import datetime

db = SQLAlchemy()
oauth = OAuth() # INITIALIZE OAUTH

# NEW: Load environment variables from .env file (for local development)
# On PythonAnywhere, these will be read from the web app's environment variables.
load_dotenv()

def create_app():
    app = Flask(__name__)



    secret_key = os.environ.get('FLASK_SECRET_KEY')
    if not secret_key:
        print("CRITICAL: SECRET_KEY is missing from environment!")
        secret_key = "a_hardcoded_backup_key_for_testing" # Only for debugging
    
    app.config['SECRET_KEY'] = secret_key
    # 1. Print ALL environment keys to see what exists
    print(f"DEBUG: Available ENV Keys: {list(os.environ.keys())}")
    
    # 2. Get credentials
    USER = os.environ.get("MYSQL_USER")           
    PASSWORD = os.environ.get("MYSQL_PASSWORD")   
    HOST = os.environ.get("MYSQL_HOST")      
    DB_NAME = os.environ.get("MYSQL_DB_NAME") 
    PORT = os.environ.get("MYSQL_PORT") 
    
    # 3. Check and Print individual values
    print(f"DEBUG: MYSQL_USER={USER}")
    print(f"DEBUG: MYSQL_HOST={HOST}")

    # DO NOT RAISE ERROR. 
    # If missing, provide a dummy string so the app can actually boot
    if not all([USER, PASSWORD, HOST, DB_NAME, PORT]):
        print("CRITICAL: MISSING ENV VARS. Using dummy values to allow boot.")
        USER, PASSWORD, HOST, DB_NAME, PORT = "dummy", "dummy", "dummy", "dummy", "3306"

    # Use PORT in the URI
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}?charset=utf8mb4'
    

    # Optional - Path to MySQL client binaries (mysqldump, mysql).
    # Get from environment variable. Leave blank on PythonAnywhere if not used/supported.
    app.config['MYSQL_BIN_PATH'] = os.environ.get('MYSQL_BIN_PATH')
    # ----------------------------------------
    
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 # 500 MB limit for file uploads

    # Security enhancements for session cookies
    app.config['SESSION_COOKIE_SECURE'] = True # Only send cookies over HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True # Prevent JavaScript access to session cookies
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # Protect against CSRF
    
    # ProxyFix is essential for deployment behind a proxy (like PythonAnywhere's Nginx)
    # It corrects URL generation and remote IP addresses.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # --- OAUTH CREDENTIALS ---
    # Get OAuth credentials from environment variables
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')  
    
    # FIX: Handle FACEBOOK_CLIENT_ID type conversion explicitly
    facebook_client_id_str = os.environ.get('FACEBOOK_CLIENT_ID')
    if facebook_client_id_str:
        try:
            app.config['FACEBOOK_CLIENT_ID'] = int(facebook_client_id_str)
        except ValueError:
            print("Warning: FACEBOOK_CLIENT_ID environment variable is not a valid integer. Setting to None.")
            app.config['FACEBOOK_CLIENT_ID'] = None # Or raise an error, or set a default.
    else:
        app.config['FACEBOOK_CLIENT_ID'] = None # Default if env var is missing entirely
        
    app.config['FACEBOOK_CLIENT_SECRET'] = os.environ.get('FACEBOOK_CLIENT_SECRET')
    # ---------------------------------------------------------
    
    # --- OAUTH CLIENT REGISTRATION (THE FIX) ---
    # This must come AFTER app config is loaded.
    oauth.init_app(app)
    
    # Register Google OAuth client if credentials are provided
    if app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'):
        oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )

    # Register Facebook OAuth client if credentials are provided
    if app.config.get('FACEBOOK_CLIENT_ID') and app.config.get('FACEBOOK_CLIENT_SECRET'):
        oauth.register(
            name='facebook',
            client_id=app.config['FACEBOOK_CLIENT_ID'],
            client_secret=app.config['FACEBOOK_CLIENT_SECRET'],
            api_base_url='https://graph.facebook.com/v19.0/',
            access_token_url='https://graph.facebook.com/oauth/access_token',
            authorize_url='https://www.facebook.com/dialog/oauth',
            client_kwargs={'scope': 'email public_profile'},
        )
    # ---------------------------------------------------------

    # Initialize APScheduler for background tasks (e.g., event reminders)
    scheduler = APScheduler()

    @scheduler.task('interval', id='event_reminders', hours=1)
    def scheduled_reminders():
        """
        This task runs inside the web application's context.
        Consider using PythonAnywhere's dedicated Scheduled Tasks for more reliability,
        especially for critical background jobs.
        """
        with app.app_context():
            from .views import check_upcoming_events
            # datetime.now() is now correctly imported
            print(f"Running scheduled event reminders at {datetime.now()}...")
            check_upcoming_events(app)
            print("Scheduled event reminders complete.")
    
    # Initialize SQLAlchemy with the Flask app
    db.init_app(app)

    # Register blueprints for different parts of the application
    from .views import views
    from .auth import auth

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')

    # Import models to ensure they are registered with SQLAlchemy
    from .models import User, ContactMessage, Booking, BlockedDate, PortfolioItem, ServicePackage, SiteSetting, SocialLink, QuickLink, InventoryItem

    # Create database tables if they don't already exist
    # For MySQL, ensure the database itself is created manually on the server (e.g., PythonAnywhere's DB tab).
    create_database(app)

    # Create a default super admin user if one doesn't already exist
    with app.app_context():
        create_admin_user()

    # Configure Flask-Login for user session management
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login' # The route name for the login page
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        """Callback to reload the user object from the user ID stored in the session."""
        return User.query.get(int(id))

    # Initialize and start the APScheduler
    scheduler.api_enabled = True # Enable the scheduler's API for dashboard views (if applicable)
    scheduler.init_app(app)
    scheduler.start()

    return app

def create_database(app):
    """
    Ensures all database tables defined in models.py are created within the configured MySQL database.
    Note: The MySQL database itself must be created manually on the server (e.g., PythonAnywhere's DB tab).
    """
    with app.app_context():
        db.create_all()
    print('Connected to database and ensured tables are created!')

def create_admin_user():
    """
    Creates a default 'superadmin' user if no user with that username exists.
    This is useful for initial setup.
    """
    from .models import User
    # Check for both 'superadmin' and 'admin' roles to prevent creating multiple default superadmins
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
        print("Super Admin Created: superadmin / admin123 (Please change this password immediately!)")
