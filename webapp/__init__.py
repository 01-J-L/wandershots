from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail # Make sure this is imported
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
import os
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import render_template
from flask_limiter.errors import RateLimitExceeded

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail() # Initialize Flask-Mail
csrf = CSRFProtect()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"] # Standard global limits
)



def create_app():
    load_dotenv()

    app = Flask(__name__)

    # In __init__.py inside create_app()
    app.config.update(
        SESSION_COOKIE_SECURE=True,     # Cookies only sent over HTTPS
        SESSION_COOKIE_HTTPONLY=True,   # Prevents JS from reading session cookies
        SESSION_COOKIE_SAMESITE='Lax',  # Helps mitigate CSRF attacks
    )

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit_exceeded(e):
        return render_template("errors/429.html", description=e.description), 429

    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # Limit upload size to 

    # Config
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or "dev_key_123"
    csrf.init_app(app)
    
    # Database Config
    db_url = os.getenv("SQLALCHEMY_DATABASE_URI") or "sqlite:///dev.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- EMAIL CONFIGURATION ---
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true' # Ensure boolean
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    sender_email = os.getenv('MAIL_USERNAME')
    app.config['MAIL_DEFAULT_SENDER'] = ("Padre Garcia Tourism", sender_email)
    # ---------------------------

    # --- FILE UPLOAD CONFIG ---
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    # -------------------------------

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app) # Initialize mail with the app
    limiter.init_app(app)
    
    login_manager.login_view = "auth.login"

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
   
    from .views import views
    from .auth import auth
    app.register_blueprint(views)
    app.register_blueprint(auth)

# Initialize DB and Create Super Admin & Seed Citizen's Charter
    with app.app_context():
        db.create_all()
        
        # Auto-create Super Admin
        admin = User.query.filter_by(email="super-admin").first()
        if not admin:
            new_admin = User(
                email="super-admin",
                first_name="Super Administrator",
                password=generate_password_hash("admin123@", method='pbkdf2:sha256'),
                is_admin=True,
                is_super_admin=True 
            )
            db.session.add(new_admin)
            db.session.commit()

        # Seed Citizen's Charter Data if empty
        from .models import CharterService, CharterRequirement, CharterStep
        if not CharterService.query.first():
            # 1. Endorsement of Tourism-Related Business
            s1 = CharterService(
                service_number=1,
                title="Endorsement of Tourism-Related Business",
                description="An endorsement of a tourism-related business is a formal expression of support, recognition, or approval given to a company or organization that operates within the tourism sector. This endorsement serves to validate the business’s credibility, service quality, and positive contribution to the local tourism industry.",
                office_division="Municipal Tourism, Culture, Arts Office",
                classification="Simple",
                transaction_type="G2X – Government to Citizens",
                who_may_avail="Entrepreneurs / Investors",
                total_processing_time="13 hours and 30 mins" # Added
            )
            db.session.add(s1)
            db.session.flush() # Flushes s1 to capture s1.id
            
            db.session.add(CharterRequirement(service_id=s1.id, requirement="Letter of Intent and Accomplished Business Plan or Proposal", where_to_secure="Municipal Tourism, Culture, and Arts Office"))
            db.session.add(CharterStep(service_id=s1.id, step_number=1, client_step="Submit Request and Documents", agency_action="Receive and evaluate completeness", fees_to_pay="None", processing_time="30mins", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s1.id, step_number=2, client_step="Review proposal and check alignment with Tourism Development Plan", agency_action="Review documents", fees_to_pay="None", processing_time="1 business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s1.id, step_number=3, client_step="Prepare endorsement letter", agency_action="Draft and sign endorsement", fees_to_pay="None", processing_time="4hours", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s1.id, step_number=4, client_step="Release of endorsement", agency_action="Release document", fees_to_pay="None", processing_time="1hour", person_responsible="Tourism Officer / Tourism Operations Assistant"))

            # 2. Request LGU Support
            s2 = CharterService(
                service_number=2,
                title="Request for LGU Support for Cultural or Artistic Events",
                description="A Request for LGU Support for Cultural or Artistic Events is a formal appeal addressed to a Local Government Unit seeking financial, logistical, promotional, or in-kind assistance for the successful organization of a cultural or artistic activity. Support from the LGU underscores its commitment to cultural development and strengthens its partnership with local organizations and creatives.",
                office_division="Municipal Tourism, Culture, Arts Office",
                classification="Simple",
                transaction_type="G2X – Government to Citizens",
                who_may_avail="Local Schools / Artists / Barangays / NGOs",
                total_processing_time="49 hours" # Added
            )
            db.session.add(s2)
            db.session.flush()
            
            db.session.add(CharterRequirement(service_id=s2.id, requirement="Request letter and an Accomplished Project Proposal or event brief", where_to_secure="Municipal Tourism, Culture, and Arts Office"))
            db.session.add(CharterStep(service_id=s2.id, step_number=1, client_step="Submit letter and proposal", agency_action="Receive – log and acknowledge", fees_to_pay="None", processing_time="1hour", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s2.id, step_number=2, client_step="Evaluate requests and availability of support", agency_action="Consult internal calendar and assess budget", fees_to_pay="None", processing_time="2-3 business days", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s2.id, step_number=3, client_step="Coordination and finalization", agency_action="Coordinate with requesting party", fees_to_pay="None", processing_time="1-2 business days", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s2.id, step_number=4, client_step="Provide support / resources", agency_action="Release approved support", fees_to_pay="None", processing_time="1business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))

            # 3. Data Requests
            s3 = CharterService(
                service_number=3,
                title="Historical/Cultural Data Requests",
                description="A Historical/Cultural Data Request is a formal appeal—often sent to archives, museums, cultural agencies, universities, or local authorities—seeking specific information, records, or resources related to a place’s history or cultural heritage.",
                office_division="Municipal Tourism, Culture, Arts Office",
                classification="Simple",
                transaction_type="G2X – Government to Citizens",
                who_may_avail="Students / Researchers / Historians",
                total_processing_time="24 hours and 30 mins" # Added
            )
            db.session.add(s3)
            db.session.flush()
            
            db.session.add(CharterRequirement(service_id=s3.id, requirement="Request letter with ID and an Accomplished Research topic or data needed", where_to_secure="Municipal Tourism, Culture, and Arts Office"))
            db.session.add(CharterStep(service_id=s3.id, step_number=1, client_step="Submit request", agency_action="Receive and acknowledge", fees_to_pay="None", processing_time="30mins", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s3.id, step_number=2, client_step="Retrieve available documents / data", agency_action="Search archives / coordinate with partners", fees_to_pay="None", processing_time="1-2 business days", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s3.id, step_number=3, client_step="Release data or schedule interview", agency_action="Notify the person requesting data", fees_to_pay="None", processing_time="1business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))

            # 4. Accreditation
            s4 = CharterService(
                service_number=4,
                title="Accreditation of Tourism Establishments",
                description="Accreditation of Tourism Establishments is a formal process conducted by a tourism authority to evaluate and recognize businesses that meet established standards for quality, safety, service, and sustainability in the tourism sector.",
                office_division="Municipal Tourism, Culture, Arts Office",
                classification="Simple",
                transaction_type="G2X – Government to Citizens",
                who_may_avail="Accommodations / Resorts / Travel Agencies / Restaurants and other tourism-related businesses",
                total_processing_time="48 hours" # Added
            )
            db.session.add(s4)
            db.session.flush()
            
            db.session.add(CharterRequirement(service_id=s4.id, requirement="Accomplished application form attached with business permit, DTI/SEC Registration, and other related documents", where_to_secure="Municipal Tourism, Culture, and Arts Office"))
            db.session.add(CharterStep(service_id=s4.id, step_number=1, client_step="Submit accreditation form and attachments", agency_action="Receive and verify documents", fees_to_pay="None", processing_time="1business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s4.id, step_number=2, client_step="Schedule inspection and evaluation", agency_action="Inspect premises", fees_to_pay="None", processing_time="2business days", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s4.id, step_number=3, client_step="Review findings", agency_action="Approve or suggest improvements", fees_to_pay="None", processing_time="2business days", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s4.id, step_number=4, client_step="Issue certificate", agency_action="Release accreditation", fees_to_pay="None", processing_time="1business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))

            # 5. Conduct of Festivals
            s5 = CharterService(
                service_number=5,
                title="Conduct of Local Festivals and Events",
                description="The Conduct of Local Festivals and Events refers to the planning, organization, and execution of community-based cultural, historical, or artistic celebrations that highlight a locality’s identity, traditions, and heritage.",
                office_division="Municipal Tourism, Culture, Arts Office",
                classification="Simple",
                transaction_type="G2X – Government to Citizens",
                who_may_avail="General Public / LGU / Barangays",
                total_processing_time="Varies per scope" # Added
            )
            db.session.add(s5)
            db.session.flush()
            
            db.session.add(CharterRequirement(service_id=s5.id, requirement="Participation form (if applicable)\nSponsorship/partnership letter (if applicable)", where_to_secure="Municipal Tourism, Culture, and Arts Office"))
            db.session.add(CharterStep(service_id=s5.id, step_number=1, client_step="Coordinate with MTCAO on event involvement", agency_action="Schedule meeting/planning session", fees_to_pay="None", processing_time="Varies", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s5.id, step_number=2, client_step="Attend orientations or briefings", agency_action="Provide event guidelines", fees_to_pay="None", processing_time="As scheduled", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s5.id, step_number=3, client_step="Participate in event", agency_action="Implement activity", fees_to_pay="None", processing_time="As scheduled", person_responsible="Tourism Officer / Tourism Operations Assistant"))

            # 6. Guided Tours
            s6 = CharterService(
                service_number=6,
                title="Guided Town Heritage Tour / Benchmarking Scheduling",
                description="A Guided Town Heritage Tour / Benchmarking Scheduling refers to the organized planning and coordination of a visit aimed at exploring a town’s historical, cultural, and architectural landmarks, often led by knowledgeable guides.",
                office_division="Municipal Tourism, Culture, Arts Office",
                classification="Simple",
                transaction_type="G2X – Government to Citizens",
                who_may_avail="Tourists / Schools / Civic Organizations",
                total_processing_time="16 hours" # Added
            )
            db.session.add(s6)
            db.session.flush()
            
            db.session.add(CharterRequirement(service_id=s6.id, requirement="Booking form and minimum 3 working days advance notice", where_to_secure="Municipal Tourism, Culture, and Arts Office"))
            db.session.add(CharterStep(service_id=s6.id, step_number=1, client_step="Request booking", agency_action="Acknowledge and confirm availability", fees_to_pay="None", processing_time="1business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s6.id, step_number=2, client_step="Arrange itinerary and tour guide", agency_action="Confirm logistics", fees_to_pay="None", processing_time="1business day", person_responsible="Tourism Officer / Tourism Operations Assistant"))
            db.session.add(CharterStep(service_id=s6.id, step_number=3, client_step="Conduct tour", agency_action="Implement tour activity", fees_to_pay="None", processing_time="As scheduled", person_responsible="Tourism Officer / Tourism Operations Assistant"))

            db.session.commit()
            

    return app