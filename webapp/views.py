from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file, abort, Response, jsonify
from flask_login import login_required, current_user
from flask_mail import Message
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from flask import jsonify

import os
import uuid
import io
import datetime 
import tempfile
import re 
import bleach
import zipfile
import shutil

from docx2pdf import convert
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import Color
import math
from reportlab.lib.utils import ImageReader
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from sqlalchemy import or_
from . import db, mail, limiter

# Update this line to include all your models
from .models import User, SiteContent, TouristSpot, Ordinance, SocialLink, FooterLink, EmergencyHotline, Mayor, Barangay, FestivalEvent, CommercialEstablishment, Accommodation, FinancialInstitution, MajorAttraction, FoodDish, SweetTreat, FestivalGalleryImage, AttractionMedia, HistoryMedia, BuildingImage, Event, Facility, DepartmentStore, CulturalProperty, CharterService, CharterRequirement, CharterStep, WebsiteView, OfficialCategory, OfficialMember

views = Blueprint("views", __name__)

# =========================================
#               TEMPLATE FILTERS
# =========================================

@views.app_template_filter('get_file_icon')
def get_file_icon(filename):
    """Returns a Remix Icon class based on the file extension."""
    if not filename:
        return 'ri-file-list-3-line'
        
    ext = filename.split('.')[-1].lower()
    
    if ext == 'pdf':
        return 'ri-file-pdf-line'
    elif ext in ['doc', 'docx']:
        return 'ri-file-word-line'
    elif ext in ['xls', 'xlsx', 'csv']:
        return 'ri-file-excel-line'
    elif ext in ['ppt', 'pptx']:
        return 'ri-file-ppt-line'
    elif ext in ['zip', 'rar', '7z', 'tar']:
        return 'ri-file-zip-line'
    elif ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp']:
        return 'ri-image-line'
    elif ext in ['mp4', 'mov', 'avi', 'webm', 'mkv']:
        return 'ri-film-line'
    else:
        return 'ri-file-list-3-line'

# =========================================
#               HELPER FUNCTIONS
# ==========================================

def get_ord_sort_key(ord_obj):
    """
    Parses ordinance numbers to sort Year Latest to Oldest (Desc), 
    then Sequence Number Ascending.
    """
    text = str(ord_obj.number).strip()
    nums = re.findall(r'\d+', text)
    if len(nums) >= 2:
        # Check which one is the 4 digit year
        if len(nums[0]) == 4:
            return (-int(nums[0]), int(nums[1]), text)
        elif len(nums[1]) == 4:
            return (-int(nums[1]), int(nums[0]), text)
        else:
            return (-int(nums[0]), int(nums[1]), text)
    elif len(nums) == 1:
        return (-int(nums[0]), 0, text)
    else:
        return (0, 0, text)


def get_font(font_size):
    """Tries to load a system scalable font. Fallbacks if running on bare Linux."""
    for font_name in ["arial.ttf", "FreeSans.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
        try:
            return ImageFont.truetype(font_name, font_size)
        except:
            continue
    return ImageFont.load_default()

def save_file(file, watermark=True):
    """
    Saves the uploaded file.
    CRITICAL: If the file is an image, it immediately bakes a "Padre Garcia Tourism"
    watermark into the bottom right corner unless watermark is set to False.
    """
    if not file or file.filename == '':
        return None
        
    filename = secure_filename(file.filename)
    unique_filename = str(uuid.uuid4()) + "_" + filename
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
    
    ext = filename.split('.')[-1].lower()
    
    # Apply baked-in watermark for Images if requested
    if ext in ['jpg', 'jpeg', 'png'] and watermark:
        try:
            img = Image.open(file.stream).convert("RGBA")
            watermark_img = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(watermark_img)
            
            text = "Padre Garcia Tourism"
            font_size = max(int(img.width * 0.035), 14) # ~3.5% of image width
            font = get_font(font_size)
            
            try:
                bbox = draw.textbbox((0,0), text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except AttributeError:
                tw, th = draw.textsize(text, font=font)
                
            x = img.width - tw - 15
            y = img.height - th - 15
            if x < 0: x = 0
            if y < 0: y = 0
            
            shadow_color = (0, 0, 0, 180)
            draw.text((x-1, y-1), text, font=font, fill=shadow_color)
            draw.text((x+1, y+1), text, font=font, fill=shadow_color)
            
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 240))
            
            out = Image.alpha_composite(img, watermark_img)
            
            if ext in ['jpg', 'jpeg']:
                out = out.convert("RGB")
                out.save(file_path, "JPEG", quality=90)
            else:
                out.save(file_path, "PNG")
        except Exception as e:
            print(f"Upload watermark error: {e}")
            file.seek(0)
            file.save(file_path)
    else:
        file.save(file_path)
        
    return f"static/uploads/{unique_filename}"

def get_content(key, default=""):
    content = SiteContent.query.filter_by(key=key).first()
    return content.value if content else default

def get_common_content():
    social_links = SocialLink.query.all()
    footer_links = FooterLink.query.all()
    hotlines = EmergencyHotline.query.all()

    return {
        'site_logo': get_content('site_logo', ''), 
        'header_bg_type': get_content('header_bg_type', 'color'),
        'header_bg_color': get_content('header_bg_color', '#0f172a'),
        'header_bg_image': get_content('header_bg_image', ''),
        'footer_brand_title': get_content('footer_brand_title', 'Tourism Padre Garcia'),
        'footer_brand_desc': get_content('footer_brand_desc', 'Promoting the culture and heritage of the Cattle Trading Capital.'),
        'footer_links_title': get_content('footer_links_title', 'Quick Links'),
        'footer_contact_title': get_content('footer_contact_title', 'Contact Us'),
        'footer_em_title': get_content('footer_em_title', 'Emergency Hotlines'),
        'contact_addr': get_content('contact_addr', '2nd Flr. LAM Bldg, Poblacion, Padre Garcia, Batangas 4224'),
        'contact_phone': get_content('contact_phone', '(043) 515-9209'),
        'contact_email': get_content('contact_email', 'tourism@padregarcia.gov.ph'),
        'footer_copyright': get_content('footer_copyright', '© 2025 Tourism Padre Garcia. All Rights Reserved.'),
        'social_links': social_links,
        'footer_links_list': footer_links,
        'hotlines_list': hotlines
    }

# =========================================
#             CONTEXT PROCESSORS
# =========================================

@views.app_context_processor
def inject_global_content():
    """
    Globally injects the base site content dictionary into every template context,
    preventing UndefinedErrors on pages that do not explicitly pass 'content'.
    """
    try:
        return dict(content=get_common_content())
    except Exception:
        # Fallback empty dictionary in case database migrations or initialization are pending
        return dict(content={})

# ==========================================
#               PUBLIC ROUTES
# ==========================================

@views.route("/")
def home():
    content = get_common_content()
    content.update({
        'hero_title_1': get_content('hero_title_1', 'Padre'),
        'hero_title_2': get_content('hero_title_2', 'Garcia'),
        'hero_subtitle': get_content('hero_subtitle', 'Discover the rich heritage and vibrant culture of the Cattle Trading Capital.'),
        'hero_image': get_content('hero_image_path', url_for('static', filename='images/municipal.jpg')),
        'hero_cta_video_path': get_content('hero_cta_video_path', ''), 
        'about_title': get_content('about_title', 'Where Tradition Meets Progress'),
        'about_text': get_content('about_text', 'Known as the Cattle Trading Capital of the Philippines, Padre Garcia is a thriving municipality in Batangas.'),
        'about_image': get_content('about_image_path', url_for('static', filename='images/municipal2.jpg')),
        'travel_title_1': get_content('travel_title_1', 'Best Time to Visit'),
        'travel_text_1': get_content('travel_text_1', 'December 1st marks our annual Kabakahan Festival.'),
        'travel_link_1': get_content('travel_link_1', ''),
        'travel_title_2': get_content('travel_title_2', 'Getting Here'),
        'travel_text_2': get_content('travel_text_2', 'Accessible via STAR Tollway (Lipa Exit) and major bus lines.'),
        'travel_link_2': get_content('travel_link_2', ''),
        'travel_title_3': get_content('travel_title_3', 'Where to Stay'),
        'travel_text_3': get_content('travel_text_3', 'We have local inns and resorts within the town proper.'),
        'travel_link_3': get_content('travel_link_3', ''),
        # --- BACKGROUND MUSIC SETTINGS ---
        'bg_music_path': get_content('bg_music_path', ''),
        'bg_music_volume': get_content('bg_music_volume', '0.5'),
    })
    page = request.args.get('page', 1, type=int)
    spots = TouristSpot.query.order_by(TouristSpot.order).paginate(page=page, per_page=8, error_out=False)
    return render_template("home.html", content=content, spots=spots)

@views.route("/search")
def global_search():
    q = request.args.get('q', '').strip()
    content = get_common_content()
    
    results = {
        'spots': [],
        'ordinances': [],
        'events': [],
        'pages': [],
        'attractions': [], 
        'history': [],     
        'commerce': [],    
        'food': [],        
        'total': 0
    }
    
    if q:
        search_term = f"%{q}%"
        
        # 1. Tourist Spots
        results['spots'] = TouristSpot.query.filter(or_(TouristSpot.name.ilike(search_term), TouristSpot.description.ilike(search_term))).all()
        
        # 2. Ordinances (With new sort logic)
        results['ordinances'] = Ordinance.query.filter(or_(Ordinance.title.ilike(search_term), Ordinance.number.ilike(search_term), Ordinance.description.ilike(search_term))).all()
        results['ordinances'] = sorted(results['ordinances'], key=get_ord_sort_key)

        # 3. Festival Events
        results['events'] = FestivalEvent.query.filter(or_(FestivalEvent.title.ilike(search_term), FestivalEvent.description.ilike(search_term), FestivalEvent.location.ilike(search_term))).all()
        
        # 4. Major Attractions
        results['attractions'] = MajorAttraction.query.filter(or_(MajorAttraction.name.ilike(search_term), MajorAttraction.description.ilike(search_term), MajorAttraction.location.ilike(search_term))).all()

        # 5. History & Heritage (Mayors + Barangays)
        mayors = Mayor.query.filter(or_(Mayor.name.ilike(search_term), Mayor.role.ilike(search_term), Mayor.years.ilike(search_term))).all()
        brgys = Barangay.query.filter(or_(Barangay.name.ilike(search_term), Barangay.captain_name.ilike(search_term))).all()
        for m in mayors:
            results['history'].append({'title': m.name, 'desc': f"Role: {m.role or 'N/A'} | Years: {m.years or 'N/A'}", 'type': 'Leader/Mayor'})
        for b in brgys:
            results['history'].append({'title': f"Barangay {b.name}", 'desc': f"Barangay Captain: {b.captain_name or 'N/A'}", 'type': 'Barangay'})

        # 6. Commerce & Lifestyle (Establishments + Accommodations + Banks)
        ests = CommercialEstablishment.query.filter(or_(CommercialEstablishment.name.ilike(search_term), CommercialEstablishment.description.ilike(search_term))).all()
        accs = Accommodation.query.filter(or_(Accommodation.name.ilike(search_term), Accommodation.description.ilike(search_term))).all()
        banks = FinancialInstitution.query.filter(FinancialInstitution.name.ilike(search_term)).all()
        for e in ests:
            results['commerce'].append({'title': e.name, 'desc': e.description, 'type': 'Dining/Shopping', 'url_anchor': '#establishments'})
        for a in accs:
            results['commerce'].append({'title': a.name, 'desc': a.description, 'type': 'Accommodation', 'url_anchor': '#accommodations'})
        for b in banks:
            results['commerce'].append({'title': b.name, 'desc': 'Financial Institution / Bank', 'type': 'Bank', 'url_anchor': ''})

        # 7. Food & Delicacies (Dishes + Sweets)
        dishes = FoodDish.query.filter(or_(FoodDish.name.ilike(search_term), FoodDish.description.ilike(search_term), FoodDish.tagline.ilike(search_term))).all()
        sweets = SweetTreat.query.filter(or_(SweetTreat.name.ilike(search_term), SweetTreat.description.ilike(search_term))).all()
        for d in dishes:
            results['food'].append({'title': d.name, 'desc': d.description, 'type': 'Local Dish'})
        for s in sweets:
            results['food'].append({'title': s.name, 'desc': s.description, 'type': 'Sweet/Pasalubong'})

        # 8. Static Pages Map (Keywords)
        pages_map = {
            'About Us': {'url': url_for('views.about'), 'icon': 'ri-information-line', 'desc': 'Discover the history, culture, and vision behind the municipality.', 'keywords': ['about', 'history', 'mission', 'vision', 'heritage', 'lumang bayan', 'mayor', 'town']},
            'History & Heritage': {'url': url_for('views.history'), 'icon': 'ri-hourglass-line', 'desc': 'Learn about Padre Vicente Garcia and the generations of Mayors.', 'keywords': ['history', 'mayor', 'vicente garcia', 'barangay', 'origin', 'heritage']},
            'Commerce & Economy': {'url': url_for('views.commercial'), 'icon': 'ri-store-2-line', 'desc': 'Explore local businesses, markets, and accommodations.', 'keywords': ['commerce', 'business', 'shopping', 'market', 'bank', 'hotel', 'stay', 'economy', 'trade']},
            'Major Attractions': {'url': url_for('views.attractions'), 'icon': 'ri-map-pin-line', 'desc': 'Major destinations including the Livestock Auction Market.', 'keywords': ['attraction', 'spot', 'tourism', 'livestock', 'market', 'park', 'bawi', 'trail', 'destination']},
            'Cultural Inventory': {'url': url_for('views.culture'), 'icon': 'ri-bank-line', 'desc': 'Sacred sites, historical monuments, and architecture.', 'keywords': ['culture', 'church', 'monument', 'parish', 'rosary', 'heritage', 'sacred', 'architecture']},
            'Kabakahan Festival': {'url': url_for('views.festival'), 'icon': 'ri-flag-line', 'desc': 'Annual cultural celebration of the Cattle Trading Capital.', 'keywords': ['festival', 'kabakahan', 'event', 'december', 'rodeo', 'celebration']},
            'Food & Delicacies': {'url': url_for('views.food'), 'icon': 'ri-restaurant-line', 'desc': 'Taste Batangas Goto, Halo-Halo, and sweet pasalubongs.', 'keywords': ['food', 'goto', 'halo-halo', 'sweet', 'pasalubong', 'delicacy', 'eat', 'taste', 'gastronomic']},
            'Contact Us': {'url': url_for('views.contacts'), 'icon': 'ri-contacts-book-line', 'desc': 'Get in touch with the Tourism Department.', 'keywords': ['contact', 'email', 'phone', 'location', 'address', 'map', 'message']},
            'Legislative Records': {'url': url_for('views.ordinances'), 'icon': 'ri-file-list-3-line', 'desc': 'Official repository of Municipal Ordinances.', 'keywords': ['ordinance', 'law', 'legal', 'resolution', 'record', 'document']},
            'Citizen\'s Charter': {'url': url_for('views.charter'), 'icon': 'ri-shield-user-line', 'desc': 'Official service standards, procedures, and processing times of the MTCAO.', 'keywords': ['charter', 'citizens', 'services', 'endorsement', 'accreditation', 'lgu support', 'tour', 'benchmarking', 'historical data', 'processing time', 'fees']}
        }
        
        q_lower = q.lower()
        q_words = q_lower.split()

        for page_name, info in pages_map.items():
            match = False
            if q_lower in page_name.lower() or q_lower in info['desc'].lower():
                match = True
            else:
                for kw in info['keywords']:
                    if any(word in kw for word in q_words) or kw in q_lower:
                        match = True
                        break
            
            if match:
                results['pages'].append({'name': page_name, 'url': info['url'], 'icon': info['icon'], 'desc': info['desc']})

        # Calculate Total Results found
        results['total'] = (len(results['spots']) + len(results['ordinances']) + len(results['events']) + 
                            len(results['pages']) + len(results['attractions']) + len(results['history']) + 
                            len(results['commerce']) + len(results['food']))

    return render_template("search_results.html", content=content, query=q, results=results)

@views.route("/about")
def about():
    content = get_common_content()
    content.update({
        'about_hero_badge': get_content('about_hero_badge', 'Welcome to Our Town'),
        'about_hero_h1': get_content('about_hero_h1', 'Our Story & Heritage'),
        'about_hero_sub': get_content('about_hero_sub', 'Discover the history, culture, and vision behind the Cattle Trading Capital.'),
        'about_intro_badge': get_content('about_intro_badge', 'About Padre Garcia'),
        'about_title': get_content('about_title', 'Where Tradition Meets Progress'),
        'about_text': get_content('about_text', 'Known as the Cattle Trading Capital of the Philippines, Padre Garcia is a thriving municipality in Batangas.'),
        'about_image': get_content('about_image_path', url_for('static', filename='images/municipal2.jpg')),
        'about_chart_path': get_content('about_chart_path', ''), 
        'about_img_caption': get_content('about_img_caption', '"A community bound by faith, hard work, and unity."'),
        'about_feat1_title': get_content('about_feat1_title', 'Rich History'),
        'about_feat1_desc': get_content('about_feat1_desc', 'Established 1949'),
        'about_feat2_title': get_content('about_feat2_title', 'Trading Hub'),
        'about_feat2_desc': get_content('about_feat2_desc', 'Economic Center'),
        'about_dir_title': get_content('about_dir_title', 'Our Direction'),
        'about_dir_sub': get_content('about_dir_sub', 'Guiding principles for a better municipality'),
        'mission_text': get_content('mission_text', 'To provide high-quality public service...'),
        'vision_text': get_content('vision_text', 'Padre Garcia shall be the premier agro-industrial center...'),
        'fact_year': get_content('fact_year', '1949'),
        'fact_year_link': get_content('fact_year_link', ''),
        'fact_barangays': get_content('fact_barangays', '18'),
        'fact_barangays_link': get_content('fact_barangays_link', ''),
        'fact_population': get_content('fact_population', '50k+'),
        'fact_population_link': get_content('fact_population_link', ''),
        'fact_festival': get_content('fact_festival', 'Dec 1'),
        'fact_festival_link': get_content('fact_festival_link', ''),
        'about_cta_title': get_content('about_cta_title', 'Experience the Warmth of Padre Garcia'),
        'about_cta_text': get_content('about_cta_text', 'Whether you are here for business, cattle trading, or leisure, our town welcomes you with open arms.'),
    })
    
    # Query categories and members mapped with ordering
    categories = OfficialCategory.query.order_by(OfficialCategory.order.asc(), OfficialCategory.id.asc()).all()
    
    return render_template("about.html", content=content, categories=categories)

# ==========================================
#         SYSTEM BACKUP & RESTORE ROUTE
# ==========================================
@views.route("/manage-backup", methods=["GET", "POST"])
@login_required
def manage_backup():
    if not current_user.is_super_admin:
        flash("Unauthorized. Only Super Administrators can perform backup/restore procedures.", "error")
        return redirect(url_for("views.dashboard"))

    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    is_sqlite = db_uri.startswith('sqlite:///')
    
    # Resolve SQLite database file location
    db_path = None
    if is_sqlite:
        db_filename = db_uri.replace('sqlite:///', '')
        paths_to_try = [
            os.path.join(current_app.instance_path, db_filename),
            os.path.join(current_app.root_path, '..', db_filename),
            os.path.join(current_app.root_path, db_filename),
            db_filename
        ]
        for path in paths_to_try:
            if os.path.exists(path):
                db_path = path
                break

    if request.method == "POST":
        # --- COMMAND A: CREATE SYSTEM ARCHIVE ZIP ---
        if "create_backup" in request.form:
            try:
                temp_dir = tempfile.gettempdir()
                backup_filename = f"padre_garcia_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                backup_path = os.path.join(temp_dir, backup_filename)
                
                with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    # 1. Safe copy & archive of SQLite database file
                    if db_path and os.path.exists(db_path):
                        temp_db = os.path.join(temp_dir, "backup_db_temp.db")
                        shutil.copy2(db_path, temp_db)
                        zip_file.write(temp_db, arcname="database.db")
                        os.remove(temp_db)
                    
                    # 2. Archive of upload folder assets
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    if os.path.exists(upload_folder):
                        for root, dirs, files in os.walk(upload_folder):
                            for file in files:
                                file_path = os.path.join(root, file)
                                archive_name = os.path.join("uploads", os.path.relpath(file_path, upload_folder))
                                zip_file.write(file_path, arcname=archive_name)
                
                return send_file(backup_path, as_attachment=True, download_name=backup_filename)
            except Exception as e:
                current_app.logger.error(f"Backup execution failed: {e}")
                flash(f"System backup failed: {e}", "error")
            return redirect(url_for("views.manage_backup"))

        # --- COMMAND B: RESTORE FROM UPLOADED ZIP ---
        if "restore_backup" in request.form:
            file = request.files.get("backup_file")
            if not file or file.filename == '':
                flash("Please upload a valid system backup zip archive.", "error")
                return redirect(url_for("views.manage_backup"))
            
            try:
                temp_dir = tempfile.gettempdir()
                zip_path = os.path.join(temp_dir, "restore_temp.zip")
                file.save(zip_path)
                
                if not zipfile.is_zipfile(zip_path):
                    flash("Invalid archive structure. The file uploaded is not a zip package.", "error")
                    return redirect(url_for("views.manage_backup"))
                    
                with zipfile.ZipFile(zip_path, 'r') as zip_file:
                    file_list = zip_file.namelist()
                    
                    # 1. Overwrite SQLite database file
                    if "database.db" in file_list:
                        if db_path:
                            # Close database engine connections to release lock handles
                            db.session.remove()
                            db.get_engine().dispose()
                            
                            zip_file.extract("database.db", temp_dir)
                            shutil.copy2(os.path.join(temp_dir, "database.db"), db_path)
                            os.remove(os.path.join(temp_dir, "database.db"))
                        else:
                            flash("Direct DB restoring is limited to SQLite. Other engines must be restored manually.", "warning")
                    
                    # 2. Restore Uploaded files directory
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    os.makedirs(upload_folder, exist_ok=True)
                    for item in file_list:
                        if item.startswith("uploads/") and not item.endswith("/"):
                            relative_path = item.replace("uploads/", "")
                            destination_path = os.path.join(upload_folder, relative_path)
                            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                            
                            with zip_file.open(item) as src, open(destination_path, "wb") as dest:
                                shutil.copyfileobj(src, dest)
                                
                os.remove(zip_path)
                flash("System files and records restored successfully.", "success")
            except Exception as e:
                current_app.logger.error(f"System recovery failed: {e}")
                flash(f"System restoration failed: {e}", "error")
            return redirect(url_for("views.manage_backup"))

    return render_template("manage_backup.html", is_sqlite=is_sqlite, db_path=db_path)

@views.route("/download/<path:filename>")
def download_watermarked(filename):
    clean_filename = filename.replace('static/uploads/', '').replace('static/images/', '').replace('static/', '')
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Resolve File Path
    full_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], clean_filename)
    if not os.path.exists(full_file_path):
        full_file_path = os.path.join(base_dir, 'static', 'images', clean_filename)
    if not os.path.exists(full_file_path):
        full_file_path = os.path.join(base_dir, 'static', clean_filename)
    
    if not os.path.exists(full_file_path):
        current_app.logger.warning(f"File not found for download: {filename}")
        abort(404)

    ext = full_file_path.split('.')[-1].lower()
    new_filename_prefix = "PG_Tourism_" 
    new_download_name = f"{new_filename_prefix}{os.path.basename(clean_filename)}"
    dl = request.args.get('dl', '0') == '1'
    temp_pdf_path = None

    # ==========================================
    # INTERCEPT: CONVERT DOCX/DOC TO PDF
    # ==========================================
    if ext in ['doc', 'docx']:
        try:
            # Create a temporary PDF file to hold the conversion
            temp_fd, temp_pdf_path = tempfile.mkstemp(suffix='.pdf')
            os.close(temp_fd) 
            
            # Convert the Word Doc to PDF
            convert(full_file_path, temp_pdf_path)
            
            # Now treat this file as a PDF for the rest of the script
            full_file_path = temp_pdf_path
            ext = 'pdf'
            
            # Change the download filename extension to .pdf
            new_download_name = new_download_name.rsplit('.', 1)[0] + '.pdf'
            
        except Exception as e:
            current_app.logger.error(f"Error converting DOCX to PDF: {e}")
            # If conversion fails, it falls back to the original docx later in the script

    # 2. Fetch the "Site Logo" from the database or use default
    logo_setting = SiteContent.query.filter_by(key='site_logo').first()
    has_logo = False
    
    if logo_setting and logo_setting.value:
        logo_path = os.path.join(current_app.root_path, logo_setting.value)
        if os.path.exists(logo_path):
            has_logo = True
            
    if not has_logo:
        logo_path = os.path.join(base_dir, 'static', 'images', 'logo_watermark.png')
        has_logo = os.path.exists(logo_path)

    def get_transparent_logo(target_width, opacity=0.50):
        if not has_logo: return None
        try:
            img = Image.open(logo_path).convert("RGBA")
            aspect_ratio = img.height / img.width
            new_width = int(target_width)
            new_height = int(new_width * aspect_ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            alpha = img.split()[3]
            alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
            img.putalpha(alpha)
            return img
        except Exception as e:
            current_app.logger.error(f"Error loading watermark logo: {e}")
            return None

    # ==========================================
    # WATERMARK IMAGES (TILED REPEAT)
    # ==========================================
    if ext in ['jpg', 'jpeg', 'png']:
        try:
            base_image = Image.open(full_file_path).convert("RGBA")
            width, height = base_image.size
            watermark_layer = Image.new("RGBA", (width, height), (0,0,0,0))
            
            if has_logo:
                logo_w = int(width * 0.15)
                if logo_w < 80: logo_w = 80 
                logo_img = get_transparent_logo(logo_w, opacity=0.25) 
                
                if logo_img:
                    logo_h = logo_img.height
                    gap_x, gap_y = int(logo_w * 0.5), int(logo_h * 0.5)
                    
                    for y in range(0, height, logo_h + gap_y):
                        for x in range(0, width, logo_w + gap_x):
                            offset_x = int((logo_w + gap_x) / 2) if (y // (logo_h + gap_y)) % 2 == 1 else 0
                            draw_x = x + offset_x
                            if draw_x < width and y < height:
                                watermark_layer.paste(logo_img, (draw_x, y), logo_img)
            else:
                draw = ImageDraw.Draw(watermark_layer)
                text = "PADRE GARCIA TOURISM"
                font_size = max(int(width * 0.04), 14)
                font = get_font(font_size)
                
                try: bbox = draw.textbbox((0,0), text, font=font); text_w, text_h = bbox[2]-bbox[0], bbox[3]-bbox[1]
                except AttributeError: text_w, text_h = draw.textsize(text, font=font)
                
                gap_x, gap_y = int(text_w * 0.3), int(text_h * 3)
                for y in range(0, height, text_h + gap_y):
                    for x in range(0, width, text_w + gap_x):
                        offset_x = int((text_w + gap_x) / 2) if (y // (text_h + gap_y)) % 2 == 1 else 0
                        draw_x = x + offset_x
                        if draw_x < width and y < height:
                            draw.text((draw_x, y), text, font=font, fill=(255, 255, 255, 90))
            
            out = Image.alpha_composite(base_image, watermark_layer)
            if ext in ['jpg', 'jpeg']:
                out = out.convert("RGB")
                save_format = 'JPEG'
            else:
                save_format = 'PNG'

            img_io = io.BytesIO()
            out.save(img_io, save_format, quality=95)
            img_io.seek(0)
            return send_file(img_io, mimetype=f'image/{save_format.lower()}', as_attachment=dl, download_name=new_download_name)
        except Exception as e:
            current_app.logger.error(f"Error watermarking image: {e}")
            return send_file(full_file_path, as_attachment=dl, download_name=new_download_name)

    # ==========================================
    # WATERMARK PDFs (TILED REPEAT)
    # ==========================================
    elif ext == 'pdf':
        try:
            # 1. READ ENTIRE PDF INTO MEMORY TO RELEASE WINDOWS FILE LOCK
            with open(full_file_path, "rb") as f:
                original_pdf_stream = io.BytesIO(f.read())
                
            # 2. DELETE THE TEMPORARY FILE IMMEDIATELY NOW THAT WE HAVE IT IN MEMORY
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
                temp_pdf_path = None # Mark as handled
                
            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=letter)
            pg_w, pg_h = letter

            if has_logo:
                logo_pil = get_transparent_logo(150, opacity=0.15)
                if logo_pil:
                    img_byte_arr = io.BytesIO()
                    logo_pil.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)
                    rl_logo = ImageReader(img_byte_arr)
                    logo_w = 150
                    logo_h = 150 * (logo_pil.height / logo_pil.width)
                    
                    gap_x, gap_y = 100, 100
                    for y in range(-int(logo_h), int(pg_h) + int(logo_h), int(logo_h + gap_y)):
                        for x in range(-int(logo_w), int(pg_w) + int(logo_w), int(logo_w + gap_x)):
                            offset_x = int((logo_w + gap_x) / 2) if (y // (logo_h + gap_y)) % 2 == 1 else 0
                            c.drawImage(rl_logo, x + offset_x, y, width=logo_w, height=logo_h, mask='auto')
            else:
                c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.15))
                c.setFont("Helvetica-Bold", 35)
                text = "PADRE GARCIA TOURISM"
                for y in range(0, int(pg_h), 200):
                    for x in range(0, int(pg_w), 300):
                        c.saveState()
                        offset = 150 if (y // 200) % 2 == 1 else 0
                        c.translate(x + offset, y)
                        c.rotate(30)
                        c.drawCentredString(0, 0, text)
                        c.restoreState()
            
            c.save()
            packet.seek(0)
            
            watermark_pdf = PdfReader(packet)
            original_pdf = PdfReader(original_pdf_stream)
            output = PdfWriter()
            
            for page in original_pdf.pages:
                page.merge_page(watermark_pdf.pages[0]) 
                output.add_page(page)
            
            out_stream = io.BytesIO()
            output.write(out_stream)
            out_stream.seek(0)
            
            return send_file(out_stream, mimetype='application/pdf', as_attachment=dl, download_name=new_download_name)
            
        except Exception as e:
            current_app.logger.error(f"Error watermarking PDF: {e}")
            
            # If an error happens, we still want to give them the unwatermarked file and clean up
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                # Read unwatermarked into memory, delete disk file, then send memory stream
                with open(temp_pdf_path, "rb") as f:
                    fallback_stream = io.BytesIO(f.read())
                os.remove(temp_pdf_path)
                return send_file(fallback_stream, mimetype='application/pdf', as_attachment=dl, download_name=new_download_name)
                
            return send_file(full_file_path, as_attachment=dl, download_name=new_download_name)

    # ==========================================
    # SERVE OTHER FILES (.xls, .ppt, failed docs) NORMALLY
    # ==========================================
    else:
        mimetype_map = {
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'ppt': 'application/vnd.ms-powerpoint',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'zip': 'application/zip',
        }
        detected_mimetype = mimetype_map.get(ext, 'application/octet-stream')
        return send_file(full_file_path, mimetype=detected_mimetype, as_attachment=dl, download_name=new_download_name)
    
@views.route("/manage-users", methods=["GET", "POST"])
@login_required
def manage_users():
    if not current_user.is_admin or not current_user.is_super_admin:
        flash("Unauthorized access.", "error")
        return redirect(url_for("views.dashboard"))

    if request.method == "POST":
        if "delete_user" in request.form:
            user_id = request.form.get("user_id")
            user_to_delete = User.query.get(user_id)
            if user_to_delete:
                if user_to_delete.id == current_user.id:
                    flash("You cannot delete your own account.", "error")
                else:
                    db.session.delete(user_to_delete)
                    db.session.commit()
                    flash("User account deleted.", "success")
            return redirect(url_for("views.manage_users"))

        if "change_password" in request.form:
            user_id = request.form.get("user_id")
            new_pass = request.form.get("new_password")
            user_to_edit = User.query.get(user_id)
            if user_to_edit and new_pass:
                hashed_password = generate_password_hash(new_pass, method='pbkdf2:sha256')
                user_to_edit.password = hashed_password
                db.session.commit()
                flash(f"Password for {user_to_edit.email} updated!", "success")
            else:
                flash("Error updating password.", "error")
            return redirect(url_for("views.manage_users"))

        if "edit_user" in request.form:
            user_id = request.form.get("user_id")
            fname = request.form.get("edit_fname")
            email = request.form.get("edit_email")
            role_type = request.form.get("edit_role") 
            user_to_edit = User.query.get(user_id)
            if user_to_edit:
                existing_email = User.query.filter_by(email=email).first()
                if existing_email and existing_email.id != int(user_id):
                    flash("That username/email is already taken.", "error")
                else:
                    user_to_edit.first_name = fname
                    user_to_edit.email = email
                    if user_to_edit.id == current_user.id and role_type != 'super':
                        flash("You cannot demote your own account.", "error")
                    else:
                        if role_type == 'super':
                            user_to_edit.is_super_admin = True
                            user_to_edit.is_admin = True
                        else:
                            user_to_edit.is_super_admin = False
                            user_to_edit.is_admin = True
                        db.session.commit()
                        flash("User details updated successfully!", "success")
            return redirect(url_for("views.manage_users"))

        if "add_sub_admin" in request.form:
            email = request.form.get("new_email")
            fname = request.form.get("new_fname")
            password = request.form.get("new_password")
            user_exists = User.query.filter_by(email=email).first()
            if user_exists:
                flash("Email already exists.", "error")
            else:
                new_user = User(
                    email=email,
                    first_name=fname,
                    password=generate_password_hash(password, method='pbkdf2:sha256'),
                    is_admin=True,
                    is_super_admin=False
                )
                db.session.add(new_user)
                db.session.commit()
                flash("New Sub-Admin created!", "success")
            return redirect(url_for("views.manage_users"))

    users = User.query.all()
    return render_template("manage_users.html", users=users)

# ==========================================
#         CITIZEN'S CHARTER ROUTES
# ==========================================

@views.route("/charter")
def charter():
    content = get_common_content()
    defaults = {
        'charter_hero_title': "Citizen's Charter",
        'charter_hero_sub': "Municipal Tourism, Culture, and Arts Office",
        'charter_hero_desc': "Our commitment to efficient, transparent, and accountable public service standards.",
        'charter_hero_bg': url_for('static', filename='images/municipal.jpg')
    }
    for k, v in defaults.items():
        content[k] = get_content(k, v)
        
    services = CharterService.query.order_by(CharterService.service_number.asc()).all()
    return render_template("charter.html", content=content, services=services)

@views.route("/edit-charter", methods=["GET", "POST"])
@login_required
def edit_charter():
    if not current_user.is_admin: 
        return redirect(url_for("views.home"))

    if request.method == "POST":
        # --- 1. UPDATE SERVICE META INFORMATION ---
        if "update_service_meta" in request.form:
            service_id = request.form.get("service_id")
            service = CharterService.query.get_or_404(service_id)
            
            service.title = request.form.get("title")
            service.description = request.form.get("description")
            service.office_division = request.form.get("office_division")
            service.classification = request.form.get("classification")
            service.transaction_type = request.form.get("transaction_type")
            service.who_may_avail = request.form.get("who_may_avail")
            service.total_processing_time = request.form.get("total_processing_time") # Added
            
            db.session.commit()
            flash(f"Meta details for service '{service.title}' updated successfully!", "success")
            return redirect(url_for("views.edit_charter", active_service=service.id))

        # --- 2. ADD REQUIREMENT ---
        if "add_requirement" in request.form:
            service_id = request.form.get("service_id")
            req_text = request.form.get("requirement")
            where_sec = request.form.get("where_to_secure")
            
            if req_text:
                new_req = CharterRequirement(
                    service_id=service_id,
                    requirement=req_text,
                    where_to_secure=where_sec
                )
                db.session.add(new_req)
                db.session.commit()
                flash("Requirement added successfully!", "success")
            return redirect(url_for("views.edit_charter", active_service=service_id))

        # --- 3. DELETE REQUIREMENT ---
        if "delete_requirement" in request.form:
            req_id = request.form.get("req_id")
            service_id = request.form.get("service_id")
            req = CharterRequirement.query.get(req_id)
            if req:
                db.session.delete(req)
                db.session.commit()
                flash("Requirement removed from checklist.", "success")
            return redirect(url_for("views.edit_charter", active_service=service_id))

        # --- 4. ADD STEP ---
        if "add_step" in request.form:
            service_id = request.form.get("service_id")
            client_step = request.form.get("client_step")
            action = request.form.get("agency_action")
            fees = request.form.get("fees_to_pay", "None")
            time_val = request.form.get("processing_time")
            responsible = request.form.get("person_responsible")
            
            # Auto calculate step order
            existing_steps_count = CharterStep.query.filter_by(service_id=service_id).count()
            
            if client_step:
                new_step = CharterStep(
                    service_id=service_id,
                    step_number=existing_steps_count + 1,
                    client_step=client_step,
                    agency_action=action,
                    fees_to_pay=fees,
                    processing_time=time_val,
                    person_responsible=responsible
                )
                db.session.add(new_step)
                db.session.commit()
                flash("New processing step added!", "success")
            return redirect(url_for("views.edit_charter", active_service=service_id))

        # --- 5. EDIT STEP ---
        if "edit_step" in request.form:
            step_id = request.form.get("step_id")
            step = CharterStep.query.get_or_404(step_id)
            
            step.client_step = request.form.get("client_step")
            step.agency_action = request.form.get("agency_action")
            step.fees_to_pay = request.form.get("fees_to_pay")
            step.processing_time = request.form.get("processing_time")
            step.person_responsible = request.form.get("person_responsible")
            step.step_number = int(request.form.get("step_number", step.step_number))
            
            db.session.commit()
            flash("Step details updated successfully!", "success")
            return redirect(url_for("views.edit_charter", active_service=step.service_id))

        # --- 6. DELETE STEP ---
        if "delete_step" in request.form:
            step_id = request.form.get("step_id")
            step = CharterStep.query.get(step_id)
            if step:
                s_id = step.service_id
                db.session.delete(step)
                db.session.commit()
                
                # Re-index step numbers
                remaining_steps = CharterStep.query.filter_by(service_id=s_id).order_by(CharterStep.step_number.asc()).all()
                for i, r_step in enumerate(remaining_steps):
                    r_step.step_number = i + 1
                db.session.commit()
                
                flash("Step deleted.", "success")
            return redirect(url_for("views.edit_charter", active_service=s_id))

    # GET Request logic
    services = CharterService.query.order_by(CharterService.service_number.asc()).all()
    active_service_id = request.args.get("active_service", type=int)
    
    selected_service = None
    if active_service_id:
        selected_service = CharterService.query.get(active_service_id)
    if not selected_service and services:
        selected_service = services[0]

    return render_template("edit_charter.html", services=services, selected_service=selected_service)

# --- PUBLIC EVENTS ROUTE ---
@views.route("/events")
def events():
    content = get_common_content()
    # Ensure current date is handled
    today = datetime.datetime.now().date()
    all_events = Event.query.order_by(Event.date.asc()).all()
    return render_template("events.html", content=content, events=all_events, today=today)

# --- ADMIN EVENTS EDITOR ROUTE ---
@views.route("/edit-events", methods=["GET", "POST"])
@login_required
def edit_events():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    
    if request.method == "POST":
        # Checkbox logic: if it's in request.form, it's True, else False
        show_date_val = True if request.form.get("show_date") else False

        # ADD EVENT
        if "add_event" in request.form:
            date_str = request.form.get("date")
            date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
            
            new_event = Event(
                title=request.form.get("title"),
                date=date_obj,
                show_date=show_date_val, # Handle new field
                description=request.form.get("desc"),
                location=request.form.get("loc"),
                image_url=save_file(request.files.get("img"))
            )
            db.session.add(new_event)
            db.session.commit()
            flash("Event added successfully!", "success")
            return redirect(url_for("views.edit_events"))
            
        # EDIT EVENT
        if "edit_event" in request.form:
            ev = Event.query.get(request.form.get("id"))
            if ev:
                ev.title = request.form.get("title")
                ev.location = request.form.get("loc")
                ev.description = request.form.get("desc")
                ev.show_date = show_date_val # Update new field
                
                date_str = request.form.get("date")
                ev.date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
                
                img_file = request.files.get("img")
                if img_file and img_file.filename != '':
                    ev.image_url = save_file(img_file)
                    
                db.session.commit()
                flash("Event updated successfully!", "success")
            return redirect(url_for("views.edit_events"))

        # DELETE EVENT
        if "delete_event" in request.form:
            ev = Event.query.get(request.form.get("id"))
            if ev:
                db.session.delete(ev)
                db.session.commit()
                flash("Event deleted.", "success")
            return redirect(url_for("views.edit_events"))
            
    events = Event.query.order_by(Event.date.asc()).all()
    return render_template("edit_events.html", events=events)

@views.route("/history")
def history():
    content = get_common_content()
    mayors = Mayor.query.order_by(Mayor.id).all()
    barangays = Barangay.query.order_by(Barangay.name).all() 
    
    # Fetch media specifically for the Padre Garcia section
    pg_media = HistoryMedia.query.filter_by(section_key='padre_garcia').order_by(HistoryMedia.order).all()

    # --- NEW: Fetch media for the 'Extra Information Section' ---
    extra_info_media = HistoryMedia.query.filter_by(section_key='history_extra_info').order_by(HistoryMedia.order).all()
    building_images = BuildingImage.query.order_by(BuildingImage.id.asc()).all()

    biography_text = """An eminent Filipino Batangueño Priest – Hero, Padre Vicente Teodoro Garcia was named after St. Vincent Ferrer by his beloved parents Don Jose Garcia and Doña Andrea Teodora of barrio Maugat, then Old Rosario (1687) now this Municipality of Padre V. Garcia (1949), Province of Batangas, Philippines.

HIS EDUCATION, DISCIPLINE AND PROFESSION:
He studied at Universidad de Sto. Tomas (Bachiller en Artes 1839; Bachiller en Teologia 1847; Doctor en Teologia 1848; Licenciado en Sagrado Teologia 1885). He also attended Real Colegio de San Jose where he earned his Bachelor of Canon and Civil Law and Doctor of Divine Theology (1849). He was ordained Priest in June 1849.

HIS NOTABLE POSITIONS, DUTIES AND APOSTOLIC WORKS:
• Rector of the Royal College of San Jose, Manila
• Chaplain of the Artillery Regiment in the Peninsular Army
• Ecclesiastical Governor at the Diocese of Nueva Caceres
• Canonigo Penetenciario and Private Consultant under Prelate of Manila Cathedral
• Founder, Hospital of the Lepers in Camarines, Bicol
• Wise Counsel (from the aged) of Philippine National Hero Dr. Jose P. Rizal

HIS WRITINGS AND AUTHORSHIP:
He authored numerous works including "Oracion Funebre" (1861), "Vida de San Eustaquio" (1875), "Aves de los Almas" (1875), "Pagtulad kay Kristo" (1880), "Pagsisiyam sa Mahal na Birhen" (1881), and "Casaysayan ng mga Cababalaghan" (1881).

HIS DEFENSE OF RIZAL:
Most notably, he wrote the Brave Defense Counter Attack Letter defending "Noli Me Tangere" (Touch Me Not) or "Huwag mo Akong Salangin" published in La Solidaridad, Vol.11, 79-80 under the pen name V. Caraig (1895).

LEGACY:
On August 7, 2017, the Sangguniang Bayan passed Ordinance No. 25-2017 declaring April 5 of every year as Padre Vicente Garcia Day to commemorate the birthdate of Padre Vicente T. Garcia."""

    defaults = {
        'hist_hero_title': 'History & Heritage', 'hist_hero_sub': 'From Lumang Bayan to Today',
        'hist_hero_img': url_for('static', filename='images/municipal.jpg'),
        'hist_org_title': 'Our Origins', 'hist_org_text': 'Originally known as Lumang Bayan...',
        'hist_build_title': 'Transformation Of Municipal Buildings', 'hist_build_sub': 'Witnessing the structural evolution...',
        'hist_b1_img': url_for('static', filename='images/firstm.jpg.jpg'), 'hist_b1_lbl': 'First Municipal Hall', 'hist_b1_desc': 'The original municipal hall of Padre Garcia.',
        'hist_b2_img': url_for('static', filename='images/firstmm.jpg.jpg'), 'hist_b2_lbl': 'After the Fire', 'hist_b2_desc': 'The rebuilt structure following the tragic fire.',
        'hist_b3_img': url_for('static', filename='images/first.jpg.jpg'), 'hist_b3_lbl': 'First Renovation', 'hist_b3_desc': 'The first major architectural renovation of the hall.',
        'hist_b4_img': url_for('static', filename='images/municipal.jpg'), 'hist_b4_lbl': 'Modern Structure', 'hist_b4_desc': 'The contemporary and modern municipal building standing today.',
        
        'hist_pg_title': 'Padre Vicente Teodoro Garcia', 
        'hist_pg_sub': 'April 05, 1817 – July 12, 1899',
        'hist_pg_sect_title': 'Life & Works', 
        'hist_pg_text': biography_text, 
        'hist_pg_img': url_for('static', filename='images/pgv.jpg.jpg'),
        'hist_pg_wiki': 'https://en.wikipedia.org/wiki/Vicente_Garc%C3%ADa',
        'hist_pg_file': '', 

        'hist_mayor_title': "Mayor's Generation", 'hist_mayor_sub': "Leaders who shaped our history",
        'hist_brgy_title': 'The 18 Barangays', 'hist_brgy_sub': 'Click on a barangay to view details',

        # --- NEW EXTRA INFO DEFAULTS ---
        'hist_extra_title': 'A Legacy of Strength',
        'hist_extra_sub': 'Cultural Resilience',
        'hist_extra_desc': 'Padre Garcia has weathered many storms and emerged stronger, a testament to the enduring spirit of its people. From colonial struggles to modern challenges, the municipality has always found its way to progress while preserving its unique identity.',
        # 'hist_extra_img': url_for('static', filename='images/municipal.jpg') # REMOVED: Now handled by HistoryMedia
    }
    for k, v in defaults.items(): content[k] = get_content(k, v)
    
    return render_template("history.html", 
                           content=content, 
                           mayors=mayors, 
                           barangays=barangays, 
                           pg_media=pg_media,
                           extra_info_media=extra_info_media,
                           building_images=building_images)

@views.route("/commercial")
def commercial():
    content = get_common_content()
    
    establishments = CommercialEstablishment.query.order_by(CommercialEstablishment.id.desc()).all()
    accommodations = Accommodation.query.order_by(Accommodation.id.desc()).all()
    department_stores = DepartmentStore.query.order_by(DepartmentStore.id.desc()).all()
    facilities = Facility.query.order_by(Facility.id.desc()).all()
    banks = FinancialInstitution.query.all()
    cultural_props = CulturalProperty.query.order_by(CulturalProperty.id.desc()).all()
    
    defaults = {
        'comm_hero_title': 'Commerce & Lifestyle', 
        'comm_hero_sub': 'Business & Leisure', 
        'comm_hero_desc': 'A growing agro-industrial hub...', 
        'comm_hero_bg': url_for('static', filename='images/commerce_hero.jpg'),
        'comm_intro_title': 'A Thriving Economy', 
        'comm_intro_text': 'Beyond the cattle market...',
        'comm_shop_title': 'Shopping & Markets', 
        'comm_shop_head': 'Padre Garcia Public Market', 
        'comm_shop_text': 'The daily heartbeat of the town...', 
        'comm_shop_img': url_for('static', filename='images/public_market.jpg'),
        'comm_shop_li1': 'Fresh Fruits & Vegetables',
        'comm_shop_li2': 'Clothing & Dry Goods',
        'comm_shop_li3': 'Agricultural Supplies',
        'comm_dine_title': 'Featured Establishments', 
        'comm_stay_title': 'Stay & Relax', 
        'comm_stay_head': 'Resorts & Inns', 
        'comm_stay_text': 'Padre Garcia offers various accommodations...', 
        'comm_fin_title': 'Financial Infrastructure', 
        'comm_fin_text': 'To support the high volume of trade, we have a robust banking system.',
        'comm_fac_title': 'Public Facilities', 
        'comm_fac_sub': 'Our Infrastructure', 
        'comm_fac_desc': 'Essential amenities.',
        'comm_dept_title': 'Department Stores', 
        'comm_dept_head': 'Shopping & Retail', 
        'comm_dept_text': 'Explore major retail centers.',
        'comm_cult_title': 'Cultural Properties', 
        'comm_cult_sub': 'Our Heritage', 
        'comm_cult_desc': 'Preserved landmarks.',

        # --- MAP FOOTER KEYS (MUST BE HERE) ---
        'comm_cuisine_map_title': 'Establishments Map', 'comm_cuisine_map_subtitle': 'Municipality of Padre Garcia',
        'comm_cuisine_map_note': '', 'comm_cuisine_map_source': '', 'comm_cuisine_map_disclaimer': '',

        'comm_stay_map_title': 'Accommodations Map', 'comm_stay_map_subtitle': 'Municipality of Padre Garcia',
        'comm_stay_map_note': '', 'comm_stay_map_source': '', 'comm_stay_map_disclaimer': '',

        'comm_dept_map_title': 'Department Stores Map', 'comm_dept_map_subtitle': 'Municipality of Padre Garcia',
        'comm_dept_map_note': '', 'comm_dept_map_source': '', 'comm_dept_map_disclaimer': '',

        'comm_fac_map_title': 'Public Facilities Map', 'comm_fac_map_subtitle': 'Municipality of Padre Garcia',
        'comm_fac_map_note': '', 'comm_fac_map_source': '', 'comm_fac_map_disclaimer': '',

        'comm_cult_map_title': 'Cultural Properties Map', 'comm_cult_map_subtitle': 'Municipality of Padre Garcia',
        'comm_cult_map_note': '', 'comm_cult_map_source': '', 'comm_cult_map_disclaimer': '',
        
        # Logos and Insets
        'attr_map_inset1': url_for('static', filename='images/placeholder.png'),
        'attr_map_inset2': url_for('static', filename='images/placeholder.png'),
        'attr_map_logo1': '', 'attr_map_logo2': '', 'attr_map_logo3': '', 'attr_map_logo4': ''
    }

    for k, v in defaults.items(): 
        content[k] = get_content(k, v)
    
    return render_template("commercial.html", 
                           content=content, 
                           establishments=establishments, 
                           accommodations=accommodations, 
                           department_stores=department_stores, 
                           banks=banks, 
                           facilities=facilities, 
                           cultural_props=cultural_props)
    
@views.route("/attractions")
def attractions():
    content = get_common_content()
    attractions_list = MajorAttraction.query.order_by(MajorAttraction.id).all()
    
    defaults = {
        'attr_hero_title': 'Major Attractions', 
        'attr_hero_bg': url_for('static', filename='images/cattle_market.jpg'),
        'attr_map_title': 'TOURIST ATTRACTIONS MAP',
        'attr_map_municipality': 'MUNICIPALITY OF PADRE GARCIA',
        'attr_map_province': 'PROVINCE OF BATANGAS',
        'attr_map_note': 'Note goes here...',
        'attr_map_source': 'Source goes here...',
        'attr_map_disclaimer': 'Disclaimer here...',
        'attr_map_inset1': url_for('static', filename='images/placeholder.png'),
        'attr_map_inset2': url_for('static', filename='images/placeholder.png'),
        'attr_map_logo1': url_for('static', filename='images/logo_watermark.png'),
        'attr_map_logo2': url_for('static', filename='images/pgv.jpg.jpg'),
        'attr_map_logo3': '', # DOT Logo URL
        'attr_map_logo4': ''  # Bagong Pilipinas URL
    }
    for k, v in defaults.items(): content[k] = get_content(k, v)
    return render_template("attractions.html", content=content, attractions=attractions_list)

@views.route('/api/attraction/<int:id>/media')
@login_required
def get_attraction_media(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
        
    attraction = MajorAttraction.query.get_or_404(id)
    media_list = [
        {
            'id': item.id,
            'url': item.media_url,
            'type': item.media_type,
            'caption': item.caption
        } 
        for item in attraction.media_items
    ]
    return jsonify({'media': media_list})

@views.route("/attraction/<int:id>")
def attraction_detail(id):
    attraction = MajorAttraction.query.get_or_404(id)
    content = get_common_content()
    return render_template("attraction_detail.html", attraction=attraction, content=content)

@views.route("/culture")
def culture():
    content = get_common_content()
    
    # 1. Defaults for the text and images on the Culture page
    defaults = {
        'cult_hero_title': 'Cultural Inventory', 
        'cult_hero_sub': 'The sacred sites...', 
        'cult_hero_tag': 'Preserving Heritage', 
        'cult_hero_bg': url_for('static', filename='images/municipal.jpg'),
        'cult_church_title': 'Most Holy Rosary Parish', 
        'cult_old_img': url_for('static', filename='images/church_old.jpg'), 
        'cult_old_lbl': 'The Old Church', 
        'cult_new_img': url_for('static', filename='images/church_new.jpg'), 
        'cult_new_lbl': 'The Modern Structure',
        'cult_hist_title': 'Historical Significance', 
        'cult_hist_text': 'The Parish stands as...', 
        'cult_arch_title': 'Architecture', 
        'cult_arch_text': 'Exterior details...',
        'cult_patron_img': url_for('static', filename='images/mama_mary.jpg'), 
        'cult_patron_title': 'Our Lady of the Most Holy Rosary', 
        'cult_patron_sub': '"The beloved patroness..."', 
        'cult_patron_text': 'The image...',
        'cult_mon_title': 'Historical Monuments', 
        'cult_mon_sub': 'Honoring Pillars',
        'cult_m1_name': 'Padre Vicente Garcia', 'cult_m1_desc': '...', 'cult_m1_img': '', 'cult_m1_pos': '50',
        'cult_m2_name': 'Hon. Graciano R. Recto', 'cult_m2_desc': '...', 'cult_m2_img': '', 'cult_m2_pos': '50',
        'cult_m3_name': 'Father Antonio', 'cult_m3_desc': '...', 'cult_m3_img': '', 'cult_m3_pos': '50'
    }
    
    # 2. Get values from SiteContent table (or fallback to defaults)
    for k, v in defaults.items(): 
        content[k] = get_content(k, v)
        
    # 3. FETCH THE DOWNLOADABLE FILES
    # We filter by the section_key 'culture_downloads' to isolate these specific files
    culture_files = HistoryMedia.query.filter_by(section_key='culture_downloads').all()
        
    # 4. Render with both the content (SiteContent) and the list of downloadable files
    return render_template("culture.html", content=content, culture_files=culture_files)

@views.route("/festival")
def festival():
    content = get_common_content()
    events = FestivalEvent.query.all() 
    page = request.args.get('page', 1, type=int)    
    gallery = FestivalGalleryImage.query.order_by(FestivalGalleryImage.id.desc()).all()
    
    defaults = {
        'fest_hero_bg': url_for('static', filename='images/festival_hero.jpg'), 
        'fest_date_badge': 'Every Dec 1', 
        'fest_hero_title': 'Kabakahan Festival', 
        'fest_hero_sub': 'Celebrating the Cattle Trading Capital',
        'fest_intro_title': 'The Spirit of the Festival', 
        'fest_intro_text': 'Annual cultural celebration...',
        'fest_c1_title': 'Culture', 'fest_c1_desc': 'Showcasing talent', 
        'fest_c2_title': 'Trade', 'fest_c2_desc': 'Boosting economy', 
        'fest_c3_title': 'Faith', 'fest_c3_desc': 'Thanksgiving',
        'fest_legal_title': 'Legal Basis', 
        'fest_legal_desc': 'Institutionalized by law...', 'fest_legal_img': url_for('static', filename='images/festival_parade.jpg'), 'fest_ord_text': 'WHEREAS...',
        'fest_prog_title': 'Program & Activities', 'fest_prog_sub': 'Highlights',
        'fest_gal_title': 'Captured Moments'
    }
    for k, v in defaults.items(): content[k] = get_content(k, v)
    return render_template("festival.html", content=content, events=events, gallery=gallery)

@views.route("/food")
def food():
    content = get_common_content()
    dishes = FoodDish.query.all()
    sweets = SweetTreat.query.all()
    
    defaults = {
        'food_hero_title': 'Gastronomic Delights', 
        'food_hero_sub': 'Taste of Padre Garcia', 
        'food_hero_desc': 'Discover the rich, savory flavors and sweet delicacies that define our culture.', 
        'food_hero_bg': url_for('static', filename='images/food_hero.jpg'),
        'food_s3_title': 'Sweets & Pasalubong', 
        'food_s3_desc': 'Take home a piece of Padre Garcia with our local treats.'
    }
    for k, v in defaults.items(): content[k] = get_content(k, v)
    return render_template("food.html", content=content, dishes=dishes, sweets=sweets)

@views.route("/ordinances")
def ordinances():
    content = get_common_content()
    ordinances_list = Ordinance.query.all()
    ordinances_list = sorted(ordinances_list, key=get_ord_sort_key)
    return render_template("ordinances.html", content=content, ordinances=ordinances_list)

@views.route("/contacts", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("100 per hour", methods=["POST"])
def contacts():
    content = get_common_content()
    defaults = {
        'contact_hero_title': 'Get in Touch', 'contact_hero_sub': "We'd love to hear from you", 'contact_hero_bg': url_for('static', filename='images/municipal.jpg'),
        'contact_card_addr_title': 'Visit Us', 'contact_card_addr_text': '2nd Flr. LAM Bldg, Poblacion...',
        'contact_card_phone_title': 'Call Us', 'contact_phone_main': '(043) 515-9209', 'contact_phone_alt': '(043) 515-7424',
        'contact_card_email_title': 'Email Us', 'contact_email_main': 'tourism@padregarcia.gov.ph', 'contact_email_alt': 'info@padregarcia.gov.ph',
        'contact_form_title': 'Send us a Message', 'contact_map_url': 'https://www.google.com/maps/embed?pb=...'
    }
    for k, v in defaults.items(): content[k] = get_content(k, v)

    if request.method == "POST":
        # Handle Form Submission Data
        name = request.form.get("sender_name")
        email = request.form.get("sender_email")
        subject = request.form.get("subject")
        message = request.form.get("message")
        
        receiver = get_content('contact_receiver_email', '')

        if not receiver:
            flash("Message could not be sent. The administrator has not configured a receiving email address yet.", "error")
        else:
            try:
                # 1. Format the sender nicely
                sender_email = current_app.config['MAIL_USERNAME']
                
                # Create the email message
                msg = Message(
                    subject=f"Website Inquiry: {subject}", # Removed brackets [] as they sometimes trigger automated filters
                    sender=("Padre Garcia Tourism", sender_email), # Formats as: "Padre Garcia Tourism" <your@email.com>
                    recipients=[receiver],
                    reply_to=(name, email) # Formats as: "User Name" <user@email.com>
                )
                
                # Render the HTML email template
                msg.html = render_template(
                    "email/contact_form_email.html",
                    name=name,
                    email=email,
                    subject=subject,
                    message=message,
                    current_year=datetime.datetime.now().year # Pass current year for footer
                )

                # Provide a plain text alternative for clients that don't render HTML
                msg.body = f"""
New message from the Padre Garcia Tourism website:

Name: {name}
Email: {email}
Subject: {subject}

Message:
{message}

---
This message was sent via your website's contact form.
Visit Padre Garcia Tourism: {url_for('views.home', _external=True)}
"""
                
                mail.send(msg)
                flash("Your message has been sent successfully!", "success")
                
            except Exception as e:
                current_app.logger.error(f"Failed to send contact form email: {e}") 
                flash("An error occurred while sending your message. Please try again later or contact us directly.", "error")
        
        return redirect(url_for('views.contacts'))

    return render_template("contact.html", content=content)

@views.route("/spot/<int:id>")
def spot_detail(id):
    spot = TouristSpot.query.get_or_404(id)
    content = get_common_content()
    return render_template("spot_detail.html", spot=spot, content=content)

@views.route("/dashboard")
@login_required
def dashboard():
    if not current_user.is_admin:
        return redirect(url_for("views.home"))
    return render_template("admin_dashboard.html", user=current_user)

@views.route("/edit-home-hero", methods=["GET", "POST"])
@login_required
def edit_home_hero():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        fields = ['hero_title_1', 'hero_title_2', 'hero_subtitle', 'bg_music_volume']
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
        
        # Save background media
        file = request.files.get("hero_image_file")
        if file and file.filename != '':
            path = save_file(file)
            existing = SiteContent.query.filter_by(key='hero_image_path').first()
            if existing: existing.value = path
            else: db.session.add(SiteContent(key='hero_image_path', value=path))
            
        # Save CTA popup video file
        file_cta = request.files.get("hero_cta_video_file")
        if file_cta and file_cta.filename != '':
            path_cta = save_file(file_cta)
            existing_cta = SiteContent.query.filter_by(key='hero_cta_video_path').first()
            if existing_cta: existing_cta.value = path_cta
            else: db.session.add(SiteContent(key='hero_cta_video_path', value=path_cta))

        # Save Background Music file
        music_file = request.files.get("bg_music_file")
        if music_file and music_file.filename != '':
            path_music = save_file(music_file)
            existing_music = SiteContent.query.filter_by(key='bg_music_path').first()
            if existing_music: existing_music.value = path_music
            else: db.session.add(SiteContent(key='bg_music_path', value=path_music))
        
        db.session.commit()
        flash("Home Hero updated!", "success")
        return redirect(url_for("views.edit_home_hero"))
    
    content = {
        'hero_title_1': get_content('hero_title_1', 'Padre'),
        'hero_title_2': get_content('hero_title_2', 'Garcia'),
        'hero_subtitle': get_content('hero_subtitle', 'Discover the rich heritage...'),
        'hero_image': get_content('hero_image_path', url_for('static', filename='images/municipal.jpg')),
        'hero_cta_video_path': get_content('hero_cta_video_path', ''),
        'bg_music_path': get_content('bg_music_path', ''),
        'bg_music_volume': get_content('bg_music_volume', '0.5')
    }
    return render_template("edit_home_hero.html", content=content)

@views.route("/edit-header", methods=["GET", "POST"])
@login_required
def edit_header():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    
    if request.method == "POST":
        # Action 1: Website Logo Upload (Watermarking disabled for branding assets)
        file = request.files.get("site_logo_file")
        if file and file.filename != '':
            path = save_file(file, watermark=False)
            existing = SiteContent.query.filter_by(key='site_logo').first()
            if existing: 
                existing.value = path
            else: 
                db.session.add(SiteContent(key='site_logo', value=path))
            
            db.session.commit()
            flash("Website Logo updated successfully!", "success")
            return redirect(url_for("views.edit_header"))
            
        # Action 2: Update Header Background configurations
        if "save_header_bg" in request.form:
            bg_type = request.form.get("header_bg_type", "color")
            bg_color = request.form.get("header_bg_color", "#0f172a")
            
            # Save Background Type choice
            existing_type = SiteContent.query.filter_by(key='header_bg_type').first()
            if existing_type: existing_type.value = bg_type
            else: db.session.add(SiteContent(key='header_bg_type', value=bg_type))
            
            # Save Color Choice value
            existing_color = SiteContent.query.filter_by(key='header_bg_color').first()
            if existing_color: existing_color.value = bg_color
            else: db.session.add(SiteContent(key='header_bg_color', value=bg_color))
            
            # Save Background Image file if uploaded (Watermarking disabled)
            file_bg = request.files.get("header_bg_file")
            if file_bg and file_bg.filename != '':
                path_bg = save_file(file_bg, watermark=False)
                existing_bg = SiteContent.query.filter_by(key='header_bg_image').first()
                if existing_bg: existing_bg.value = path_bg
                else: db.session.add(SiteContent(key='header_bg_image', value=path_bg))
                
            db.session.commit()
            flash("Header background settings updated successfully!", "success")
            return redirect(url_for("views.edit_header"))

        # Action 3: Reset background configurations to solid Slate defaults
        if "reset_bg" in request.form:
            for key in ['header_bg_type', 'header_bg_color', 'header_bg_image']:
                item = SiteContent.query.filter_by(key=key).first()
                if item:
                    db.session.delete(item)
            db.session.commit()
            flash("Header settings reverted back to default parameters.", "success")
            return redirect(url_for("views.edit_header"))
            
    content = {
        'site_logo': get_content('site_logo', ''),
        'header_bg_type': get_content('header_bg_type', 'color'),
        'header_bg_color': get_content('header_bg_color', '#0f172a'),
        'header_bg_image': get_content('header_bg_image', '')
    }
    return render_template("edit_header.html", content=content)

@views.route("/edit-about-teaser", methods=["GET", "POST"])
@login_required
def edit_about_teaser():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        fields = ['about_title', 'about_text'] 
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
        file = request.files.get("about_image_file")
        if file and file.filename != '':
            path = save_file(file)
            existing = SiteContent.query.filter_by(key='about_image_path').first()
            if existing: existing.value = path
            else: db.session.add(SiteContent(key='about_image_path', value=path))
        db.session.commit()
        flash("About Teaser updated!", "success")
        return redirect(url_for("views.edit_about_teaser"))
    content = {
        'about_title': get_content('about_title', 'Where Tradition Meets Progress'),
        'about_text': get_content('about_text', 'Known as the Cattle Trading Capital...'),
        'about_image_path': get_content('about_image_path', url_for('static', filename='images/municipal2.jpg'))
    }
    return render_template("edit_about_teaser.html", content=content)

@views.route("/manage-spots", methods=["GET", "POST"])
@login_required
def manage_spots():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        if "add_spot" in request.form:
            name = request.form.get("spot_name")
            desc = request.form.get("spot_desc")
            link = request.form.get("spot_link")
            file = request.files.get("spot_image_file")
            final_path = None
            if file and file.filename != '': final_path = save_file(file)
            if name and final_path:
                db.session.add(TouristSpot(name=name, image_url=final_path, description=desc, link_url=link))
                flash("Spot added successfully!", "success")
            else:
                flash("Name and Image are required.", "error")
        elif "edit_spot" in request.form:
            spot_id = request.form.get("spot_id")
            spot = TouristSpot.query.get(spot_id)
            if spot:
                spot.name = request.form.get("spot_name")
                spot.description = request.form.get("spot_desc")
                spot.link_url = request.form.get("spot_link")
                file = request.files.get("spot_image_file")
                if file and file.filename != '':
                    new_path = save_file(file)
                    spot.image_url = new_path
                db.session.commit()
                flash(f"{spot.name} updated successfully!", "success")
            else:
                flash("Spot not found.", "error")
        elif "delete_spot" in request.form:
            spot_id = request.form.get("spot_id")
            spot = TouristSpot.query.get(spot_id)
            if spot:
                db.session.delete(spot)
                flash("Spot deleted.", "success")
        db.session.commit()
        return redirect(url_for("views.manage_spots"))
    spots = TouristSpot.query.order_by(TouristSpot.id.desc()).all()
    return render_template("manage_spots.html", spots=spots)

@views.route("/manage-ordinances", methods=["GET", "POST"])
@login_required
def manage_ordinances():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        if "add_ordinance" in request.form:
            num = request.form.get("ord_number")
            title = request.form.get("ord_title")
            desc = request.form.get("ord_desc")
            files = request.files.getlist("ord_file")
            
            paths = []
            for f in files:
                if f and f.filename != '':
                    path = save_file(f)
                    if path: paths.append(path)
                    
            file_url = "|".join(paths) if paths else None
            
            if num and title:
                db.session.add(Ordinance(number=num, title=title, description=desc, file_url=file_url))
                flash("Ordinance added successfully!", "success")
            else:
                flash("Number and Title are required.", "error")
                
        elif "edit_ordinance" in request.form:
            ord_id = request.form.get("ord_id")
            ordinance = Ordinance.query.get(ord_id)
            if ordinance:
                ordinance.number = request.form.get("ord_number")
                ordinance.title = request.form.get("ord_title")
                ordinance.description = request.form.get("ord_desc")
                
                files = request.files.getlist("ord_file")
                new_paths = []
                for f in files:
                    if f and f.filename != '':
                        path = save_file(f)
                        if path: new_paths.append(path)
                        
                if new_paths:
                    existing = ordinance.file_url.split('|') if ordinance.file_url else []
                    existing.extend(new_paths)
                    ordinance.file_url = "|".join(existing)
                    
                db.session.commit()
                flash("Ordinance updated successfully!", "success")
                
        elif "delete_ord_file" in request.form:
            ord_id = request.form.get("ord_id")
            file_path = request.form.get("file_path")
            ordinance = Ordinance.query.get(ord_id)
            if ordinance and ordinance.file_url:
                paths = ordinance.file_url.split('|')
                if file_path in paths:
                    paths.remove(file_path)
                    ordinance.file_url = "|".join(paths) if paths else None
                    db.session.commit()
                    flash("File removed.", "success")
                    
        elif "delete_ordinance" in request.form:
            ord_id = request.form.get("ord_id")
            ordinance = Ordinance.query.get(ord_id)
            if ordinance:
                db.session.delete(ordinance)
                flash("Ordinance deleted.", "success")
                
        db.session.commit()
        return redirect(url_for("views.manage_ordinances"))
        
    ordinances = Ordinance.query.all()
    ordinances = sorted(ordinances, key=get_ord_sort_key)
    return render_template("manage_ordinances.html", ordinances=ordinances)

@views.before_app_request
def check_maintenance():
    try:
        setting = SiteContent.query.filter_by(key='site_maintenance_mode').first()
        is_maintenance = (setting.value == 'true') if setting else False
    except:
        is_maintenance = False
    if not is_maintenance:
        return None
    if (request.endpoint and 'static' in request.endpoint) or \
       (request.endpoint == 'views.maintenance') or \
       (request.endpoint and 'auth.' in request.endpoint):
        return None
    if current_user.is_authenticated and current_user.is_super_admin:
        return None
    return redirect(url_for('views.maintenance'))

# ==========================================
#         VISITOR VIEW TRACKING HOOK
# ==========================================
@views.before_app_request
def track_visitor():
    # Exclude non-GET requests, static files, and admin actions
    if request.method != 'GET':
        return
    
    if request.endpoint:
        if 'static' in request.endpoint:
            return
        # Skip count if visiting admin/management interfaces
        admin_endpoints = ['dashboard', 'edit_', 'manage_', 'site_settings', 'auth.', 'check_maintenance', 'maintenance', 'download']
        if any(x in request.endpoint for x in admin_endpoints):
            return

    try:
        # Check if tracking setting is turned on (defaults to true)
        tracking_setting = SiteContent.query.filter_by(key='track_views_enabled').first()
        is_enabled = (tracking_setting.value == 'true') if tracking_setting else True
        
        if is_enabled:
            new_view = WebsiteView()
            db.session.add(new_view)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging visitor view: {e}")

# ==========================================
#           ADMIN ANALYTICS ROUTE
# ==========================================
@views.route("/manage-analytics", methods=["GET", "POST"])
@login_required
def manage_analytics():
    if not current_user.is_admin:
        return redirect(url_for("views.home"))

    # Handle control commands (Stop / Continue counting)
    if request.method == "POST":
        if "toggle_tracking" in request.form:
            status = request.form.get("tracking_status")  # 'true' or 'false'
            setting = SiteContent.query.filter_by(key='track_views_enabled').first()
            if setting:
                setting.value = status
            else:
                db.session.add(SiteContent(key='track_views_enabled', value=status))
            db.session.commit()
            flash(f"Website tracking has been {'enabled' if status == 'true' else 'disabled'}.", "success")
        return redirect(url_for("views.manage_analytics"))

    # Fetch configuration
    tracking_setting = SiteContent.query.filter_by(key='track_views_enabled').first()
    is_enabled = tracking_setting.value if tracking_setting else 'true'

    # Total hits counter
    total_views = WebsiteView.query.count()

    # Parse custom range filters (GET query parameters)
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()

    now = datetime.datetime.now()
    default_from = now - datetime.timedelta(days=30)
    default_to = now

    from_date = default_from
    to_date = default_to

    if from_date_str:
        try:
            from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d')
        except ValueError:
            from_date_str = ""
    if to_date_str:
        try:
            to_date = datetime.datetime.strptime(to_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            to_date_str = ""

    active_from_str = from_date_str if from_date_str else from_date.strftime('%Y-%m-%d')
    active_to_str = to_date_str if to_date_str else to_date.strftime('%Y-%m-%d')

    # Query filtered hit counts within specific date range
    filtered_views = WebsiteView.query.filter(
        WebsiteView.timestamp >= from_date,
        WebsiteView.timestamp <= to_date
    ).count()

    # Dynamic CSV Export Execution
    if request.args.get('export') == 'csv':
        import csv
        views_list = WebsiteView.query.filter(
            WebsiteView.timestamp >= from_date,
            WebsiteView.timestamp <= to_date
        ).order_by(WebsiteView.timestamp.asc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Record ID', 'Timestamp (Server Time/UTC)'])
        for v in views_list:
            writer.writerow([v.id, v.timestamp.strftime('%Y-%m-%d %H:%M:%S')])
        
        response = Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=website_views_{active_from_str}_to_{active_to_str}.csv"}
        )
        return response

    # Aggregate metric structures (Sliding windows for Chart.js)
    day_labels = []
    day_data = []
    for i in range(6, -1, -1):
        day = now - datetime.timedelta(days=i)
        start_of_day = datetime.datetime(day.year, day.month, day.day, 0, 0, 0)
        end_of_day = datetime.datetime(day.year, day.month, day.day, 23, 59, 59)
        count = WebsiteView.query.filter(WebsiteView.timestamp >= start_of_day, WebsiteView.timestamp <= end_of_day).count()
        day_labels.append(day.strftime("%b %d"))
        day_data.append(count)

    week_labels = []
    week_data = []
    for i in range(7, -1, -1):
        target_week = now - datetime.timedelta(weeks=i)
        start_week = target_week - datetime.timedelta(days=target_week.weekday())
        start_week_dt = datetime.datetime(start_week.year, start_week.month, start_week.day, 0, 0, 0)
        end_week_dt = start_week_dt + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)
        count = WebsiteView.query.filter(WebsiteView.timestamp >= start_week_dt, WebsiteView.timestamp <= end_week_dt).count()
        week_labels.append(f"Wk {start_week.strftime('%W (%b %d)')}")
        week_data.append(count)

    month_labels = []
    month_data = []
    for i in range(11, -1, -1):
        year_offset = (now.month - i - 1) // 12
        month_idx = (now.month - i - 1) % 12 + 1
        year_idx = now.year + year_offset
        
        start_month = datetime.datetime(year_idx, month_idx, 1, 0, 0, 0)
        if month_idx == 12:
            end_month = datetime.datetime(year_idx + 1, 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
        else:
            end_month = datetime.datetime(year_idx, month_idx + 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
        
        count = WebsiteView.query.filter(WebsiteView.timestamp >= start_month, WebsiteView.timestamp <= end_month).count()
        month_labels.append(start_month.strftime("%b %Y"))
        month_data.append(count)

    year_labels = []
    year_data = []
    for i in range(4, -1, -1):
        year_val = now.year - i
        start_year = datetime.datetime(year_val, 1, 1, 0, 0, 0)
        end_year = datetime.datetime(year_val, 12, 31, 23, 59, 59)
        count = WebsiteView.query.filter(WebsiteView.timestamp >= start_year, WebsiteView.timestamp <= end_year).count()
        year_labels.append(str(year_val))
        year_data.append(count)

    analytics_data = {
        'day': {'labels': day_labels, 'data': day_data},
        'week': {'labels': week_labels, 'data': week_data},
        'month': {'labels': month_labels, 'data': month_data},
        'year': {'labels': year_labels, 'data': year_data}
    }

    return render_template("manage_analytics.html", 
                           is_enabled=is_enabled, 
                           total_views=total_views, 
                           analytics_data=analytics_data,
                           filtered_views=filtered_views,
                           active_from_str=active_from_str,
                           active_to_str=active_to_str)

@views.route("/maintenance")
def maintenance():
    if get_content('site_maintenance_mode', 'false') != 'true':
        return redirect(url_for('views.home'))
    if current_user.is_authenticated and current_user.is_super_admin:
        flash("Maintenance Mode is active, but you have Super Admin access.", "warning")
        return redirect(url_for('views.dashboard'))
    return render_template("maintenance.html")

@views.route("/site-settings", methods=["GET", "POST"])
@login_required
def site_settings():
    if not current_user.is_super_admin:
        flash("Unauthorized. Only Super Admins can access Global Settings.", "error")
        return redirect(url_for("views.dashboard"))
    
    if request.method == "POST":
        # HANDLE MAINTENANCE MODE TOGGLE
        if "toggle_maintenance" in request.form:
            mode = request.form.get("maintenance_mode")
            status = 'true' if mode else 'false'
            content = SiteContent.query.filter_by(key='site_maintenance_mode').first()
            if content:
                content.value = status
            else:
                db.session.add(SiteContent(key='site_maintenance_mode', value=status))
            db.session.commit()
            if status == 'true':
                flash("Maintenance Mode ENABLED. The public site is now locked.", "warning")
            else:
                flash("Maintenance Mode DISABLED. The site is now live.", "success")
            return redirect(url_for("views.site_settings"))

        # HANDLE CONTACT EMAIL RECEIVER UPDATE
        if "update_receiver_email" in request.form:
            email = request.form.get("receiver_email")
            # Basic email validation (you might want more robust validation)
            if "@" not in email or "." not in email:
                flash("Please enter a valid email address.", "error")
            else:
                content = SiteContent.query.filter_by(key='contact_receiver_email').first()
                if content:
                    content.value = email
                else:
                    db.session.add(SiteContent(key='contact_receiver_email', value=email))
                db.session.commit()
                flash("Contact form receiver email updated successfully.", "success")
            return redirect(url_for("views.site_settings"))

    current_status = get_content('site_maintenance_mode', 'false')
    receiver_email = get_content('contact_receiver_email', '')
    return render_template("site_settings.html", maintenance_mode=current_status, receiver_email=receiver_email)

@views.route("/edit-footer", methods=["GET", "POST"])
@login_required
def edit_footer():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        if "add_social" in request.form:
            platform = request.form.get("platform_name")
            url = request.form.get("platform_url")
            icon = request.form.get("platform_icon")
            if platform and url:
                new_link = SocialLink(platform=platform, url=url, icon=icon)
                db.session.add(new_link)
                db.session.commit()
                flash("Social link added!", "success")
            else:
                flash("Platform Name and URL are required.", "error")
            return redirect(url_for("views.edit_footer"))
        if "delete_social" in request.form:
            link_id = request.form.get("link_id")
            link = SocialLink.query.get(link_id)
            if link:
                db.session.delete(link)
                db.session.commit()
                flash("Social link deleted.", "success")
            return redirect(url_for("views.edit_footer"))
        if "add_quick_link" in request.form:
            label = request.form.get("link_label")
            url = request.form.get("link_url")
            if label and url:
                new_fl = FooterLink(label=label, url=url)
                db.session.add(new_fl)
                db.session.commit()
                flash("Footer link added!", "success")
            return redirect(url_for("views.edit_footer"))
        if "delete_quick_link" in request.form:
            fl_id = request.form.get("fl_id")
            link = FooterLink.query.get(fl_id)
            if link:
                db.session.delete(link)
                db.session.commit()
                flash("Footer link deleted.", "success")
            return redirect(url_for("views.edit_footer"))
        elif "edit_quick_link" in request.form:
            fl_id = request.form.get("link_id")
            link = FooterLink.query.get(fl_id)
            if link:
                link.label = request.form.get("link_label")
                link.url = request.form.get("link_url")
                db.session.commit()
                flash("Link updated successfully!", "success")
            return redirect(url_for("views.edit_footer"))
        if "add_hotline" in request.form:
            name = request.form.get("hotline_name")
            num = request.form.get("hotline_num")
            if name and num:
                new_hl = EmergencyHotline(name=name, number=num)
                db.session.add(new_hl)
                db.session.commit()
                flash("Hotline added!", "success")
            return redirect(url_for("views.edit_footer"))
        if "delete_hotline" in request.form:
            hl_id = request.form.get("hl_id")
            hotline = EmergencyHotline.query.get(hl_id)
            if hotline:
                db.session.delete(hotline)
                db.session.commit()
                flash("Hotline deleted.", "success")
            return redirect(url_for("views.edit_footer"))
        elif "edit_hotline" in request.form:
            hl_id = request.form.get("hotline_id")
            hotline = EmergencyHotline.query.get(hl_id)
            if hotline:
                hotline.name = request.form.get("hotline_name")
                hotline.number = request.form.get("hotline_num")
                db.session.commit()
                flash("Hotline updated successfully!", "success")
            return redirect(url_for("views.edit_footer"))
        else:
            fields = [
                'footer_brand_title', 'footer_brand_desc',
                'footer_links_title', 'footer_contact_title', 
                'contact_addr', 'contact_phone', 'contact_email',
                'footer_em_title', 'footer_copyright'
            ]
            for field in fields:
                val = request.form.get(field)
                if val is not None:
                    existing = SiteContent.query.filter_by(key=field).first()
                    if existing: existing.value = val
                    else: db.session.add(SiteContent(key=field, value=val))
            db.session.commit()
            flash("Footer settings updated!", "success")
            return redirect(url_for("views.edit_footer"))
    content = get_common_content() 
    return render_template("edit_footer.html", content=content)

@views.route("/edit-travel", methods=["GET", "POST"])
@login_required
def edit_travel():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        fields = [
            'travel_title_1', 'travel_text_1', 'travel_link_1', 
            'travel_title_2', 'travel_text_2', 'travel_link_2', 
            'travel_title_3', 'travel_text_3', 'travel_link_3'
        ]
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
        db.session.commit()
        flash("Travel Info updated!", "success")
        return redirect(url_for("views.edit_travel"))
    content = {
        'travel_title_1': get_content('travel_title_1', 'Best Time to Visit'),
        'travel_text_1': get_content('travel_text_1', 'December 1st marks our Kabakahan Festival...'),
        'travel_link_1': get_content('travel_link_1', ''),
        'travel_title_2': get_content('travel_title_2', 'Getting Here'),
        'travel_text_2': get_content('travel_text_2', 'Accessible via STAR Tollway (Lipa Exit)...'),
        'travel_link_2': get_content('travel_link_2', ''),
        'travel_title_3': get_content('travel_title_3', 'Where to Stay'),
        'travel_text_3': get_content('travel_text_3', 'We have local inns within the town proper...'),
        'travel_link_3': get_content('travel_link_3', ''),
    }
    return render_template("edit_travel.html", content=content)

@views.route("/edit-about", methods=["GET", "POST"])
@login_required
def edit_about():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    
    if request.method == "POST":
        # --- SUB-ACTION 1: ADD CATEGORY ---
        if "add_category" in request.form:
            name = request.form.get("cat_name")
            order_val = int(request.form.get("cat_order", 0))
            if name:
                db.session.add(OfficialCategory(name=name, order=order_val))
                db.session.commit()
                flash("New directory category added successfully!", "success")
            return redirect(url_for("views.edit_about"))

        # --- SUB-ACTION 2: EDIT CATEGORY ---
        if "edit_category" in request.form:
            cat = OfficialCategory.query.get(request.form.get("cat_id"))
            if cat:
                cat.name = request.form.get("cat_name")
                cat.order = int(request.form.get("cat_order", 0))
                db.session.commit()
                flash("Category details updated successfully!", "success")
            return redirect(url_for("views.edit_about"))

        # --- SUB-ACTION 3: DELETE CATEGORY ---
        if "delete_category" in request.form:
            cat = OfficialCategory.query.get(request.form.get("cat_id"))
            if cat:
                db.session.delete(cat)
                db.session.commit()
                flash("Category and all belonging members deleted.", "success")
            return redirect(url_for("views.edit_about"))

        # --- SUB-ACTION 4: ADD MEMBER ---
        if "add_member" in request.form:
            cat_id = request.form.get("category_id")
            name = request.form.get("mem_name")
            title = request.form.get("mem_title")
            order_val = int(request.form.get("mem_order", 0))
            
            file = request.files.get("mem_image")
            img_path = save_file(file, watermark=False) if file else None # Avoid watermarking headshots
            
            if cat_id and name:
                new_mem = OfficialMember(
                    category_id=cat_id,
                    name=name,
                    title=title,
                    image_url=img_path,
                    order=order_val
                )
                db.session.add(new_mem)
                db.session.commit()
                flash("New member added to the directory!", "success")
            return redirect(url_for("views.edit_about"))

        # --- SUB-ACTION 5: EDIT MEMBER ---
        if "edit_member" in request.form:
            mem = OfficialMember.query.get(request.form.get("mem_id"))
            if mem:
                mem.category_id = request.form.get("category_id")
                mem.name = request.form.get("mem_name")
                mem.title = request.form.get("mem_title")
                mem.order = int(request.form.get("mem_order", 0))
                
                file = request.files.get("mem_image")
                if file and file.filename != '':
                    mem.image_url = save_file(file, watermark=False)
                    
                db.session.commit()
                flash("Member details updated successfully!", "success")
            return redirect(url_for("views.edit_about"))

        # --- SUB-ACTION 6: DELETE MEMBER ---
        if "delete_member" in request.form:
            mem = OfficialMember.query.get(request.form.get("mem_id"))
            if mem:
                db.session.delete(mem)
                db.session.commit()
                flash("Member removed from directory.", "success")
            return redirect(url_for("views.edit_about"))

        # --- STANDARD TEXT AND STATIC PAGE FIELDS ---
        fields = [
            'about_hero_badge', 'about_hero_h1', 'about_hero_sub',
            'about_intro_badge', 'about_title', 'about_text', 'about_img_caption',
            'about_feat1_title', 'about_feat1_desc', 
            'about_feat2_title', 'about_feat2_desc',
            'about_dir_title', 'about_dir_sub',
            'mission_text', 'vision_text',
            'fact_year', 'fact_year_link', 
            'fact_barangays', 'fact_barangays_link', 
            'fact_population', 'fact_population_link', 
            'fact_festival', 'fact_festival_link',
            'about_cta_title', 'about_cta_text'
        ]
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
        
        # Featured Image
        file = request.files.get("about_image_file")
        if file and file.filename != '':
            path = save_file(file)
            existing = SiteContent.query.filter_by(key='about_image_path').first()
            if existing: existing.value = path
            else: db.session.add(SiteContent(key='about_image_path', value=path))

        # Tourism Arrivals Chart
        chart_file = request.files.get("about_chart_file")
        if chart_file and chart_file.filename != '':
            chart_path = save_file(chart_file)
            existing_chart = SiteContent.query.filter_by(key='about_chart_path').first()
            if existing_chart: 
                existing_chart.value = chart_path
            else: 
                db.session.add(SiteContent(key='about_chart_path', value=chart_path))

        db.session.commit()
        flash("About Page updated successfully!", "success")
        return redirect(url_for("views.edit_about"))

    # GET REQUEST
    content = {
        'about_hero_badge': get_content('about_hero_badge', 'Welcome to Our Town'),
        'about_hero_h1': get_content('about_hero_h1', 'Our Story & Heritage'),
        'about_hero_sub': get_content('about_hero_sub', 'Discover the history, culture, and vision...'),
        'about_intro_badge': get_content('about_intro_badge', 'About Padre Garcia'),
        'about_title': get_content('about_title', 'Where Tradition Meets Progress'),
        'about_text': get_content('about_text', 'Known as the Cattle Trading Capital...'),
        'about_image_path': get_content('about_image_path', url_for('static', filename='images/municipal2.jpg')),
        'about_chart_path': get_content('about_chart_path', ''), 
        'about_img_caption': get_content('about_img_caption', '"A community bound by faith, hard work, and unity."'),
        'about_feat1_title': get_content('about_feat1_title', 'Rich History'),
        'about_feat1_desc': get_content('about_feat1_desc', 'Established 1949'),
        'about_feat2_title': get_content('about_feat2_title', 'Trading Hub'),
        'about_feat2_desc': get_content('about_feat2_desc', 'Economic Center'),
        'about_dir_title': get_content('about_dir_title', 'Our Direction'),
        'about_dir_sub': get_content('about_dir_sub', 'Guiding principles for a better municipality'),
        'mission_text': get_content('mission_text', 'To provide high-quality public service...'),
        'vision_text': get_content('vision_text', 'Padre Garcia shall be the premier agro-industrial...'),
        'fact_year': get_content('fact_year', '1949'),
        'fact_year_link': get_content('fact_year_link', ''),
        'fact_barangays': get_content('fact_barangays', '18'),
        'fact_barangays_link': get_content('fact_barangays_link', ''),
        'fact_population': get_content('fact_population', '50k+'),
        'fact_population_link': get_content('fact_population_link', ''),
        'fact_festival': get_content('fact_festival', 'Dec 1'),
        'fact_festival_link': get_content('fact_festival_link', ''),
        'about_cta_title': get_content('about_cta_title', 'Experience the Warmth of Padre Garcia'),
        'about_cta_text': get_content('about_cta_text', 'Whether you are here for business, cattle trading...'),
    }

    categories = OfficialCategory.query.order_by(OfficialCategory.order.asc(), OfficialCategory.id.asc()).all()
    return render_template("about_us_edit.html", content=content, categories=categories)

# ==========================================
#               ADMIN ROUTES
# ==========================================

@views.route("/edit-history", methods=["GET", "POST"])
@login_required
def edit_history():
    if not current_user.is_admin: return redirect(url_for("views.home"))

    biography_text = """An eminent Filipino Batangueño Priest – Hero, Padre Vicente Teodoro Garcia was named after St. Vincent Ferrer by his beloved parents Don Jose Garcia and Doña Andrea Teodora of barrio Maugat, then Old Rosario (1687) now this Municipality of Padre V. Garcia (1949), Province of Batangas, Philippines.

HIS EDUCATION, DISCIPLINE AND PROFESSION:
He studied at Universidad de Sto. Tomas (Bachiller en Artes 1839; Bachiller en Teologia 1847; Doctor en Teologia 1848; Licenciado en Sagrado Teologia 1885). He also attended Real Colegio de San Jose where he earned his Bachelor of Canon and Civil Law and Doctor of Divine Theology (1849). He was ordained Priest in June 1849.

HIS NOTABLE POSITIONS, DUTIES AND APOSTOLIC WORKS:
• Rector of the Royal College of San Jose, Manila
• Chaplain of the Artillery Regiment in the Peninsular Army
• Ecclesiastical Governor at the Diocese of Nueva Caceres
• Canonigo Penetenciario and Private Consultant under Prelate of Manila Cathedral
• Founder, Hospital of the Lepers in Camarines, Bicol
• Wise Counsel (from the aged) of Philippine National Hero Dr. Jose P. Rizal

HIS WRITINGS AND AUTHORSHIP:
He authored numerous works including "Oracion Funebre" (1861), "Vida de San Eustaquio" (1875), "Aves de los Almas" (1875), "Pagtulad kay Kristo" (1880), "Pagsisiyam sa Mahal na Birhen" (1881), and "Casaysayan ng mga Cababalaghan" (1881).

HIS DEFENSE OF RIZAL:
Most notably, he wrote the Brave Defense Counter Attack Letter defending "Noli Me Tangere" (Touch Me Not) or "Huwag mo Akong Salangin" published in La Solidaridad, Vol.11, 79-80 under the pen name V. Caraig (1895).

LEGACY:
On August 7, 2017, the Sangguniang Bayan passed Ordinance No. 25-2017 declaring April 5 of every year as Padre Vicente Garcia Day to commemorate the birthdate of Padre Vicente T. Garcia."""

    if request.method == "POST":
        # --- Handle Mayor Forms ---
        if "add_mayor" in request.form:
            name = request.form.get("mayor_name")
            role = request.form.get("mayor_role")
            years = request.form.get("mayor_years")
            description = request.form.get("mayor_desc")
            file = request.files.get("mayor_img")
            final_path = save_file(file) if file and file.filename != '' else url_for('static', filename='images/placeholder_mayor.jpg')
            if name:
                db.session.add(Mayor(name=name, role=role, years=years, description=description, image_url=final_path))
                db.session.commit()
                flash("New Mayor added!", "success")
            return redirect(url_for("views.edit_history"))

        if "edit_mayor" in request.form:
            mayor = Mayor.query.get_or_404(request.form.get("mayor_id"))
            mayor.name = request.form.get("mayor_name")
            mayor.role = request.form.get("mayor_role")
            mayor.years = request.form.get("mayor_years")
            mayor.description = request.form.get("mayor_desc")
            file = request.files.get("mayor_img")
            if file and file.filename != '':
                mayor.image_url = save_file(file)
            db.session.commit()
            flash("Mayor details updated!", "success")
            return redirect(url_for("views.edit_history"))

        if "delete_mayor" in request.form:
            mayor = Mayor.query.get_or_404(request.form.get("mayor_id"))
            db.session.delete(mayor)
            db.session.commit()
            flash("Mayor deleted.", "success")
            return redirect(url_for("views.edit_history"))

        # --- Handle Barangay Forms ---
        if "add_barangay" in request.form:
            name = request.form.get("brgy_name")
            lat_val = request.form.get("brgy_lat")
            lng_val = request.form.get("brgy_lng")
            
            new_brgy = Barangay(
                name=name,
                captain_name=request.form.get("brgy_captain"),
                map_url=request.form.get("brgy_map"),
                lat=float(lat_val) if lat_val else None,
                lng=float(lng_val) if lng_val else None,
                captain_image=save_file(request.files.get("brgy_img")) if request.files.get("brgy_img") else None
            )
            db.session.add(new_brgy)
            db.session.commit()
            flash(f"Added {name}!", "success")
            return redirect(url_for("views.edit_history"))

        if "edit_barangay" in request.form:
            brgy = Barangay.query.get_or_404(request.form.get("brgy_id"))
            brgy.name = request.form.get("brgy_name")
            brgy.captain_name = request.form.get("brgy_captain")
            brgy.map_url = request.form.get("brgy_map")
            
            lat_val = request.form.get("brgy_lat")
            lng_val = request.form.get("brgy_lng")
            brgy.lat = float(lat_val) if lat_val else None
            brgy.lng = float(lng_val) if lng_val else None

            file = request.files.get("brgy_img")
            if file and file.filename != '':
                brgy.captain_image = save_file(file)
            db.session.commit()
            flash(f"Updated {brgy.name}!", "success")
            return redirect(url_for("views.edit_history"))
        
        if "delete_barangay" in request.form:
            brgy = Barangay.query.get_or_404(request.form.get("brgy_id"))
            db.session.delete(brgy)
            db.session.commit()
            flash("Barangay deleted.", "success")
            return redirect(url_for("views.edit_history"))
        
        # --- Handle History Media Upload (Gallery) ---
        if "add_history_media" in request.form:
            files = request.files.getlist("media_files")
            caption = request.form.get("media_caption")
            section_key = request.form.get("section_key") 
            for file in files:
                if file and file.filename != '':
                    path = save_file(file)
                    ext = file.filename.split('.')[-1].lower()
                    media_type = 'video' if ext in ['mp4', 'mov', 'webm'] else 'image'
                    new_media = HistoryMedia(section_key=section_key, media_url=path, media_type=media_type, caption=caption)
                    db.session.add(new_media)
            db.session.commit()
            flash(f"Added new media item(s).", "success")
            return redirect(url_for("views.edit_history"))

        if "update_history_media_caption" in request.form:
            media_item = HistoryMedia.query.get_or_404(request.form.get("media_id"))
            media_item.caption = request.form.get("media_caption")
            db.session.commit()
            flash("Image description updated!", "success")
            return redirect(url_for("views.edit_history"))

        if "delete_history_media" in request.form:
            media_item = HistoryMedia.query.get_or_404(request.form.get("media_id"))
            db.session.delete(media_item)
            db.session.commit()
            flash("Media item deleted.", "success")
            return redirect(url_for("views.edit_history"))
        
        if "add_building_img" in request.form:
            file = request.files.get("building_img")
            label = request.form.get("b_label")
            desc = request.form.get("b_desc")
            if file and file.filename != '':
                path = save_file(file)
                new_b = BuildingImage(label=label, description=desc, image_url=path)
                db.session.add(new_b)
                db.session.commit()
                flash("Carousel item added!", "success")
            return redirect(url_for("views.edit_history"))
        
        if "edit_building_img" in request.form:
            b_id = request.form.get("b_id")
            building = BuildingImage.query.get_or_404(b_id)
            building.label = request.form.get("b_label")
            building.description = request.form.get("b_desc")
            
            file = request.files.get("building_img")
            if file and file.filename != '':
                building.image_url = save_file(file)
                
            db.session.commit()
            flash("Building details updated!", "success")
            return redirect(url_for("views.edit_history"))

        if "delete_building_img" in request.form:
            b = BuildingImage.query.get_or_404(request.form.get("b_id"))
            db.session.delete(b)
            db.session.commit()
            flash("Removed from carousel.", "success")
            return redirect(url_for("views.edit_history"))

        # --- Handle Main Static Content (Save All Changes Button) ---
        if "update_main_content" in request.form:
            pdf_file = request.files.get("hist_pg_pdf")
            if pdf_file and pdf_file.filename != '':
                path = save_file(pdf_file)
                existing = SiteContent.query.filter_by(key='hist_pg_file').first()
                if existing: existing.value = path
                else: db.session.add(SiteContent(key='hist_pg_file', value=path))

            fields = [
                'hist_hero_title', 'hist_hero_sub', 'hist_org_title', 'hist_org_text',
                'hist_build_title', 'hist_build_sub', 'hist_b1_lbl', 'hist_b2_lbl', 'hist_b3_lbl', 'hist_b4_lbl',
                'hist_b1_desc', 'hist_b2_desc', 'hist_b3_desc', 'hist_b4_desc',
                'hist_pg_title', 'hist_pg_sub', 'hist_pg_sect_title', 'hist_pg_text', 'hist_pg_wiki',
                'hist_mayor_title', 'hist_mayor_sub', 'hist_brgy_title', 'hist_brgy_sub',
                'hist_extra_title', 'hist_extra_sub', 'hist_extra_desc'
            ]
            for field in fields:
                val = request.form.get(field)
                if val is not None:
                    existing = SiteContent.query.filter_by(key=field).first()
                    if existing: existing.value = val
                    else: db.session.add(SiteContent(key=field, value=val))

            img_fields = ['hist_hero_img', 'hist_pg_img', 'hist_b1_img', 'hist_b2_img', 'hist_b3_img', 'hist_b4_img']
            for field in img_fields:
                file = request.files.get(field + "_file")
                if file and file.filename != '':
                    path = save_file(file)
                    existing = SiteContent.query.filter_by(key=field).first()
                    if existing: existing.value = path
                    else: db.session.add(SiteContent(key=field, value=path))

            db.session.commit()
            flash("History Page updated successfully!", "success")
            return redirect(url_for("views.edit_history"))

    # GET Request
    mayors_list = Mayor.query.order_by(Mayor.id).all()
    barangays_list = Barangay.query.order_by(Barangay.name).all()
    pg_media = HistoryMedia.query.filter_by(section_key='padre_garcia').order_by(HistoryMedia.id.desc()).all()
    extra_info_media = HistoryMedia.query.filter_by(section_key='history_extra_info').order_by(HistoryMedia.id.desc()).all()
    building_images = BuildingImage.query.order_by(BuildingImage.id.asc()).all()

    defaults = {
        'hist_hero_title': 'History & Heritage', 'hist_hero_sub': 'From Lumang Bayan to Today',
        'hist_hero_img': url_for('static', filename='images/municipal.jpg'),
        'hist_org_title': 'Our Origins', 'hist_org_text': 'Originally known as Lumang Bayan...',
        'hist_build_title': 'Transformation Of Municipal Buildings', 'hist_build_sub': 'Witnessing the structural evolution...',
        'hist_b1_img': url_for('static', filename='images/firstm.jpg.jpg'), 'hist_b1_lbl': 'First Municipal Hall', 'hist_b1_desc': 'The original municipal hall of Padre Garcia.',
        'hist_b2_img': url_for('static', filename='images/firstmm.jpg.jpg'), 'hist_b2_lbl': 'After the Fire', 'hist_b2_desc': 'The rebuilt structure following the tragic fire.',
        'hist_b3_img': url_for('static', filename='images/first.jpg.jpg'), 'hist_b3_lbl': 'First Renovation', 'hist_b3_desc': 'The first major architectural renovation of the hall.',
        'hist_b4_img': url_for('static', filename='images/municipal.jpg'), 'hist_b4_lbl': 'Modern Structure', 'hist_b4_desc': 'The contemporary and modern municipal building standing today.',
        'hist_pg_title': 'Padre Vicente Teodoro Garcia', 'hist_pg_sub': 'April 05, 1817 – July 12, 1899',
        'hist_pg_sect_title': 'Life & Works', 'hist_pg_text': biography_text, 
        'hist_pg_img': url_for('static', filename='images/pgv.jpg.jpg'), 'hist_pg_wiki': 'https://en.wikipedia.org/wiki/Vicente_Garc%C3%ADa',
        'hist_pg_file': '', 'hist_mayor_title': "Mayor's Generation", 'hist_mayor_sub': "Leaders who shaped our history",
        'hist_brgy_title': 'The 18 Barangays', 'hist_brgy_sub': 'Click on a barangay to view details',
        'hist_extra_title': 'A Legacy of Strength', 'hist_extra_sub': 'Cultural Resilience', 'hist_extra_desc': 'Padre Garcia has weathered many storms...',
    }
    
    content = {}
    for k, v in defaults.items(): content[k] = get_content(k, v)
    
    return render_template("edit_history.html", content=content, mayors=mayors_list, barangays=barangays_list, pg_media=pg_media, extra_info_media=extra_info_media, building_images=building_images)

@views.route("/edit-commerce", methods=["GET", "POST"])
@login_required
def edit_commerce():
    if not current_user.is_admin: 
        return redirect(url_for("views.home"))
    
    if request.method == "POST":
        # Handle Dynamic Data (Establishments, Accs, Dept, Banks, Fac, Cult)
        if "add_est" in request.form:
            new_est = CommercialEstablishment(
                name=request.form.get("est_name"), 
                description=request.form.get("est_desc"), 
                map_url=request.form.get("est_map"),
                lat=float(request.form.get("est_lat")) if request.form.get("est_lat") else None,
                lng=float(request.form.get("est_lng")) if request.form.get("est_lng") else None,
                image_url=save_file(request.files.get("est_img")) if request.files.get("est_img") else None
            )
            db.session.add(new_est)
            db.session.commit()
            flash("Establishment added!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "edit_est" in request.form:
            est = CommercialEstablishment.query.get(request.form.get("est_id"))
            if est:
                est.name, est.description, est.map_url = request.form.get("est_name"), request.form.get("est_desc"), request.form.get("est_map")
                est.lat = float(request.form.get("est_lat")) if request.form.get("est_lat") else None
                est.lng = float(request.form.get("est_lng")) if request.form.get("est_lng") else None
                if request.files.get("est_img") and request.files.get("est_img").filename != '': 
                    est.image_url = save_file(request.files.get("est_img"))
                db.session.commit()
                flash("Establishment updated!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "delete_est" in request.form:
            est = CommercialEstablishment.query.get(request.form.get("est_id"))
            if est: db.session.delete(est); db.session.commit()
            return redirect(url_for("views.edit_commerce"))

        if "add_acc" in request.form:
            new_acc = Accommodation(
                name=request.form.get("acc_name"), description=request.form.get("acc_desc"), map_url=request.form.get("acc_map"),
                lat=float(request.form.get("acc_lat")) if request.form.get("acc_lat") else None,
                lng=float(request.form.get("acc_lng")) if request.form.get("acc_lng") else None,
                image_url=save_file(request.files.get("acc_img")) if request.files.get("acc_img") else None
            )
            db.session.add(new_acc); db.session.commit(); flash("Accommodation added!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "edit_acc" in request.form:
            acc = Accommodation.query.get(request.form.get("acc_id"))
            if acc:
                acc.name, acc.description, acc.map_url = request.form.get("acc_name"), request.form.get("acc_desc"), request.form.get("acc_map")
                acc.lat, acc.lng = float(request.form.get("acc_lat")) if request.form.get("acc_lat") else None, float(request.form.get("acc_lng")) if request.form.get("acc_lng") else None
                if request.files.get("acc_img") and request.files.get("acc_img").filename != '': acc.image_url = save_file(request.files.get("acc_img"))
                db.session.commit(); flash("Accommodation updated!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "delete_acc" in request.form:
            acc = Accommodation.query.get(request.form.get("acc_id"))
            if acc: db.session.delete(acc); db.session.commit()
            return redirect(url_for("views.edit_commerce"))

        if "add_dept" in request.form:
            new_dept = DepartmentStore(
                name=request.form.get("dept_name"), description=request.form.get("dept_desc"), map_url=request.form.get("dept_map"),
                lat=float(request.form.get("dept_lat")) if request.form.get("dept_lat") else None,
                lng=float(request.form.get("dept_lng")) if request.form.get("dept_lng") else None,
                image_url=save_file(request.files.get("dept_img")) if request.files.get("dept_img") else None
            )
            db.session.add(new_dept); db.session.commit(); flash("Department Store added!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "edit_dept" in request.form:
            dept = DepartmentStore.query.get(request.form.get("dept_id"))
            if dept:
                dept.name, dept.description, dept.map_url = request.form.get("dept_name"), request.form.get("dept_desc"), request.form.get("dept_map")
                dept.lat, dept.lng = float(request.form.get("dept_lat")) if request.form.get("dept_lat") else None, float(request.form.get("dept_lng")) if request.form.get("dept_lng") else None
                if request.files.get("dept_img") and request.files.get("dept_img").filename != '': dept.image_url = save_file(request.files.get("dept_img"))
                db.session.commit(); flash("Department Store updated!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "delete_dept" in request.form:
            dept = DepartmentStore.query.get(request.form.get("dept_id"))
            if dept: db.session.delete(dept); db.session.commit()
            return redirect(url_for("views.edit_commerce"))

        if "add_bank" in request.form:
            db.session.add(FinancialInstitution(name=request.form.get("bank_name"), url=request.form.get("bank_url"))); db.session.commit(); flash("Institution added!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "edit_bank" in request.form:
            bank = FinancialInstitution.query.get(request.form.get("bank_id"))
            if bank: bank.name, bank.url = request.form.get("bank_name"), request.form.get("bank_url"); db.session.commit(); flash("Institution updated!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "delete_bank" in request.form:
            bank = FinancialInstitution.query.get(request.form.get("bank_id"))
            if bank: db.session.delete(bank); db.session.commit()
            return redirect(url_for("views.edit_commerce"))

        if "add_facility" in request.form:
            new_fac = Facility(
                name=request.form.get("name"), description=request.form.get("description"), category=request.form.get("category"), map_url=request.form.get("map_url"),
                lat=float(request.form.get("fac_lat")) if request.form.get("fac_lat") else None,
                lng=float(request.form.get("fac_lng")) if request.form.get("fac_lng") else None,
                image_url=save_file(request.files.get("img")) if request.files.get("img") else None
            )
            db.session.add(new_fac); db.session.commit(); flash("Facility added!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "edit_facility" in request.form:
            fac = Facility.query.get(request.form.get("fac_id"))
            if fac:
                fac.name, fac.description, fac.category, fac.map_url = request.form.get("name"), request.form.get("description"), request.form.get("category"), request.form.get("map_url")
                fac.lat, fac.lng = float(request.form.get("fac_lat")) if request.form.get("fac_lat") else None, float(request.form.get("fac_lng")) if request.form.get("fac_lng") else None
                if request.files.get("img") and request.files.get("img").filename != '': fac.image_url = save_file(request.files.get("img"))
                db.session.commit(); flash("Facility updated!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "delete_facility" in request.form:
            fac = Facility.query.get(request.form.get("fac_id"))
            if fac: db.session.delete(fac); db.session.commit(); flash("Facility deleted.", "success")
            return redirect(url_for("views.edit_commerce"))

        if "add_cult" in request.form:
            new_cp = CulturalProperty(
                name=request.form.get("cult_name"), description=request.form.get("cult_desc"), map_url=request.form.get("cult_map"),
                lat=float(request.form.get("cult_lat")) if request.form.get("cult_lat") else None,
                lng=float(request.form.get("cult_lng")) if request.form.get("cult_lng") else None,
                image_url=save_file(request.files.get("cult_img")) if request.files.get("cult_img") else None
            )
            db.session.add(new_cp); db.session.commit(); flash("Cultural Property added!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "edit_cult" in request.form:
            cp = CulturalProperty.query.get(request.form.get("cult_id"))
            if cp:
                cp.name, cp.description, cp.map_url = request.form.get("cult_name"), request.form.get("cult_desc"), request.form.get("cult_map")
                cp.lat, cp.lng = float(request.form.get("cult_lat")) if request.form.get("cult_lat") else None, float(request.form.get("cult_lng")) if request.form.get("cult_lng") else None
                if request.files.get("cult_img") and request.files.get("cult_img").filename != '': cp.image_url = save_file(request.files.get("cult_img"))
                db.session.commit(); flash("Cultural Property updated!", "success")
            return redirect(url_for("views.edit_commerce"))

        if "delete_cult" in request.form:
            cp = CulturalProperty.query.get(request.form.get("cult_id"))
            if cp: db.session.delete(cp); db.session.commit(); flash("Cultural Property removed.", "success")
            return redirect(url_for("views.edit_commerce"))

        # --- Handle Static Content (Global Save Button) ---
        fields = [
            'comm_hero_title', 'comm_hero_sub', 'comm_hero_desc',
            'comm_intro_title', 'comm_intro_text',
            'comm_shop_title', 'comm_shop_head', 'comm_shop_text',
            'comm_shop_li1', 'comm_shop_li2', 'comm_shop_li3',
            'comm_dine_title',
            'comm_stay_title', 'comm_stay_head', 'comm_stay_text',
            'comm_fin_title', 'comm_fin_text',
            'comm_fac_title', 'comm_fac_sub', 'comm_fac_desc',
            'comm_dept_title', 'comm_dept_head', 'comm_dept_text',
            'comm_cult_title', 'comm_cult_sub', 'comm_cult_desc',
            
            # --- MAP FOOTER TITLE & SUBTITLE ---
            'comm_cuisine_map_title', 'comm_cuisine_map_subtitle',
            'comm_stay_map_title', 'comm_stay_map_subtitle',
            'comm_dept_map_title', 'comm_dept_map_subtitle',
            'comm_fac_map_title', 'comm_fac_map_subtitle',
            'comm_cult_map_title', 'comm_cult_map_subtitle',

            # --- MAP FOOTER NOTES & SOURCES ---
            'comm_cuisine_map_note', 'comm_cuisine_map_source',
            'comm_stay_map_note', 'comm_stay_map_source',
            'comm_dept_map_note', 'comm_dept_map_source',
            'comm_fac_map_note', 'comm_fac_map_source',
            'comm_cult_map_note', 'comm_cult_map_source',

            # --- THE MISSING DISCLAIMERS ---
            'comm_cuisine_map_disclaimer',
            'comm_stay_map_disclaimer',
            'comm_dept_map_disclaimer',
            'comm_fac_map_disclaimer',
            'comm_cult_map_disclaimer'
        ]
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
        
        img_fields = ['comm_hero_bg', 'comm_shop_img']
        for field in img_fields:
            file = request.files.get(field + "_file")
            if file and file.filename != '':
                path = save_file(file)
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = path
                else: db.session.add(SiteContent(key=field, value=path))
                
        db.session.commit(); flash("Page content updated!", "success")
        return redirect(url_for("views.edit_commerce"))

    # GET Request
    defaults = {
        'comm_hero_title': 'Commerce & Lifestyle', 'comm_hero_sub': 'Business & Leisure', 'comm_hero_desc': 'A growing agro-industrial hub...', 
        'comm_hero_bg': url_for('static', filename='images/commerce_hero.jpg'),
        'comm_intro_title': 'A Thriving Economy', 'comm_intro_text': 'Beyond the cattle market...',
        'comm_shop_title': 'Shopping & Markets', 'comm_shop_head': 'Padre Garcia Public Market', 'comm_shop_text': 'The daily heartbeat of the town...', 'comm_shop_img': url_for('static', filename='images/public_market.jpg'),
        'comm_shop_li1': 'Fresh Fruits & Vegetables', 'comm_shop_li2': 'Clothing & Dry Goods', 'comm_shop_li3': 'Agricultural Supplies',
        'comm_dine_title': 'Featured Establishments', 'comm_stay_title': 'Stay & Relax', 'comm_stay_head': 'Resorts & Inns', 'comm_stay_text': 'Padre Garcia offers various accommodations...',
        'comm_fin_title': 'Financial Infrastructure', 'comm_fin_text': 'To support the high volume of trade...',
        'comm_fac_title': 'Public Facilities', 'comm_fac_sub': 'Our Infrastructure', 'comm_fac_desc': 'Essential amenities.',
        'comm_dept_title': 'Department Stores', 'comm_dept_head': 'Shopping & Retail', 'comm_dept_text': 'Explore major retail centers.',
        'comm_cult_title': 'Cultural Properties', 'comm_cult_sub': 'Our Heritage', 'comm_cult_desc': 'Preserved landmarks.',
        # Map Footer Defaults
        'comm_cuisine_map_title': 'Establishments Map', 'comm_cuisine_map_subtitle': 'Municipality of Padre Garcia', 'comm_cuisine_map_note': 'Map displays verified commercial and dining establishments.', 'comm_cuisine_map_source': 'BPLO Records', 'comm_cuisine_map_disclaimer': 'Locations are indicative.',
        'comm_stay_map_title': 'Accommodations Map', 'comm_stay_map_subtitle': 'Municipality of Padre Garcia', 'comm_stay_map_note': 'Map displays accredited resorts and inns.', 'comm_stay_map_source': 'Tourism Office', 'comm_stay_map_disclaimer': 'Booking in advance recommended.',
        'comm_dept_map_title': 'Department Stores Map', 'comm_dept_map_subtitle': 'Municipality of Padre Garcia', 'comm_dept_map_note': 'Retail hubs and department stores.', 'comm_dept_map_source': 'BPLO Records', 'comm_dept_map_disclaimer': 'Approximate locations.',
        'comm_fac_map_title': 'Public Facilities Map', 'comm_fac_map_subtitle': 'Municipality of Padre Garcia', 'comm_fac_map_note': 'Health units and government offices.', 'comm_fac_map_source': 'Municipal Engineering', 'comm_fac_map_disclaimer': 'See footer for hotlines.',
        'comm_cult_map_title': 'Cultural Properties Map', 'comm_cult_map_subtitle': 'Municipality of Padre Garcia', 'comm_cult_map_note': 'Significant historical sites.', 'comm_cult_map_source': 'Tourism Office', 'comm_cult_map_disclaimer': 'Preserved landmarks.'
    }
    content = {k: get_content(k, v) for k, v in defaults.items()}
    # Logos and insets for map board logic
    for k in ['attr_map_logo1', 'attr_map_logo2', 'attr_map_logo3', 'attr_map_logo4', 'attr_map_inset1', 'attr_map_inset2']: content[k] = get_content(k, '')
    
    return render_template("edit_commerce.html", content=content, cultural_props=CulturalProperty.query.order_by(CulturalProperty.id.desc()).all(), establishments=CommercialEstablishment.query.order_by(CommercialEstablishment.id.desc()).all(), accommodations=Accommodation.query.order_by(Accommodation.id.desc()).all(), banks=FinancialInstitution.query.order_by(FinancialInstitution.id.desc()).all(), facilities=Facility.query.order_by(Facility.id.desc()).all(), department_stores=DepartmentStore.query.order_by(DepartmentStore.id.desc()).all())

@views.route("/edit-attractions", methods=["GET", "POST"])
@login_required
def edit_attractions():
    if not current_user.is_admin: 
        return redirect(url_for("views.home"))

    ALLOWED_TAGS = [
        'h2', 'h3', 'p', 'div', 'span', 'ul', 'ol', 'li', 'img', 'br', 'strong', 'em', 'a'
    ]
    ALLOWED_ATTRIBUTES = {
        'img': ['src', 'alt', 'class', 'style'],
        'div': ['class', 'style'],
        'span': ['class', 'style'],
        'a': ['href', 'target', 'class']
    }

    if request.method == "POST":
        # Get and sanitize full_content safely only during POST requests
        raw_content = request.form.get("attr_full_content")
        clean_content = ""
        if raw_content is not None:
            clean_content = bleach.clean(raw_content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
        
        # --- Handle Main Attraction Edits ---
        if "add_attr" in request.form:
            new_attr = MajorAttraction(
                name=request.form.get("attr_name"), 
                tag=request.form.get("attr_tag"),
                description=request.form.get("attr_desc"), 
                location=request.form.get("attr_loc"),
                map_url=request.form.get("attr_map"), 
                full_content=clean_content, # Uses the sanitized clean_content
                lat=float(request.form.get("attr_lat")) if request.form.get("attr_lat") else None,
                lng=float(request.form.get("attr_lng")) if request.form.get("attr_lng") else None,
                media_url=save_file(request.files.get("attr_media")) if request.files.get("attr_media") else None
            )
            db.session.add(new_attr)
            db.session.commit()
            flash("Attraction added successfully!", "success")
            return redirect(url_for("views.edit_attractions"))

        if "edit_attr" in request.form:
            attr = MajorAttraction.query.get_or_404(request.form.get("attr_id"))
            attr.name = request.form.get("attr_name")
            attr.tag = request.form.get("attr_tag")
            attr.description = request.form.get("attr_desc")
            attr.location = request.form.get("attr_loc")
            attr.map_url = request.form.get("attr_map")
            attr.full_content = clean_content # Uses the sanitized clean_content
            
            attr.lat = float(request.form.get("attr_lat")) if request.form.get("attr_lat") else None
            attr.lng = float(request.form.get("attr_lng")) if request.form.get("attr_lng") else None
            
            file = request.files.get("attr_media")
            if file and file.filename != '': 
                attr.media_url = save_file(file)
                
            db.session.commit()
            flash("Attraction details updated!", "success")
            return redirect(url_for("views.edit_attractions"))

        # --- Handle Gallery Media Upload (Images/Videos) ---
        if "add_gallery_media" in request.form:
            attraction_id = request.form.get("attraction_id")
            attraction = MajorAttraction.query.get_or_404(attraction_id)
            files = request.files.getlist("gallery_files")
            caption = request.form.get("media_caption")

            for file in files:
                if file and file.filename != '':
                    path = save_file(file)
                    ext = file.filename.split('.')[-1].lower()
                    media_type = 'video' if ext in ['mp4', 'mov', 'webm'] else 'image'

                    new_media = AttractionMedia(
                        attraction_id=attraction_id,
                        media_url=path,
                        media_type=media_type,
                        caption=caption
                    )
                    db.session.add(new_media)
            db.session.commit()
            flash(f"Added new gallery media to {attraction.name}.", "success")
            return redirect(url_for("views.edit_attractions"))
        
        # --- Handle Downloadable Files Upload (PDFs, Docs, etc.) ---
        if "add_download_file" in request.form:
            attraction_id = request.form.get("attraction_id")
            attraction = MajorAttraction.query.get_or_404(attraction_id)
            files = request.files.getlist("download_files")
            caption = request.form.get("file_caption")

            for file in files:
                if file and file.filename != '':
                    path = save_file(file)
                    
                    new_media = AttractionMedia(
                        attraction_id=attraction_id,
                        media_url=path,
                        media_type='file',
                        caption=caption
                    )
                    db.session.add(new_media)
            db.session.commit()
            flash(f"Added downloadable file(s) to {attraction.name}.", "success")
            return redirect(url_for("views.edit_attractions"))
        
        # --- Handle Media Deletion (For both visual media and files) ---
        if "delete_media" in request.form:
            media_id = request.form.get("media_id")
            media_item = AttractionMedia.query.get_or_404(media_id)
            
            try:
                if media_item.media_url:
                    file_path = os.path.join(current_app.root_path, media_item.media_url)
                    if os.path.exists(file_path):
                        os.remove(file_path)
            except Exception as e:
                current_app.logger.error(f"Error deleting file {media_item.media_url}: {e}")

            db.session.delete(media_item)
            db.session.commit()
            flash("Media/File item deleted.", "success")
            return redirect(url_for("views.edit_attractions"))

        # --- Static Content Handler ---
        fields = [
            'attr_hero_title', 'attr_hero_sub', 'attr_hero_desc', 
            'attr_map_title', 'attr_map_municipality', 'attr_map_province',
            'attr_map_note', 'attr_map_source', 'attr_map_disclaimer'
        ]

        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))

        img_map = {
            'attr_hero_bg': 'attr_hero_bg_file',
            'attr_map_inset1': 'attr_map_inset1_file',
            'attr_map_inset2': 'attr_map_inset2_file',
            'attr_map_logo1': 'attr_map_logo1_file',
            'attr_map_logo2': 'attr_map_logo2_file',
            'attr_map_logo3': 'attr_map_logo3_file',
            'attr_map_logo4': 'attr_map_logo4_file'
        }

        for db_key, form_name in img_map.items():
            file = request.files.get(form_name)
            if file and file.filename != '':
                path = save_file(file)
                existing = SiteContent.query.filter_by(key=db_key).first()
                if existing: 
                    existing.value = path
                else: 
                    db.session.add(SiteContent(key=db_key, value=path))
                
        db.session.commit()
        flash("Attractions Page static content updated!", "success")
        return redirect(url_for("views.edit_attractions"))

    # --- GET Request Logic ---
    defaults = {
        'attr_hero_title': 'Major Attractions', 
        'attr_hero_sub': 'Pride of the Town', 
        'attr_hero_desc': 'From our economic heart to our natural wonders.', 
        'attr_hero_bg': url_for('static', filename='images/cattle_market.jpg'),
        'attr_map_sub': 'Explore our local attractions on the map',
        'attr_map_title': 'TOURIST ATTRACTIONS MAP',
        'attr_map_municipality': 'MUNICIPALITY OF PADRE GARCIA',
        'attr_map_province': 'PROVINCE OF BATANGAS',
        'attr_map_note': '',
        'attr_map_source': '',
        'attr_map_disclaimer': '',
        'attr_map_inset1': '',
        'attr_map_inset2': '',
        'attr_map_logo1': '',
        'attr_map_logo2': '',
        'attr_map_logo3': '',
        'attr_map_logo4': ''
    }
    content = {}
    for k, v in defaults.items(): 
        content[k] = get_content(k, v)
    
    attractions_list = MajorAttraction.query.order_by(MajorAttraction.id.desc()).all()
    
    return render_template("edit_attractions.html", content=content, attractions=attractions_list)

@views.route("/edit-culture", methods=["GET", "POST"])
@login_required
def edit_culture():
    if not current_user.is_admin: 
        return redirect(url_for("views.home"))

    if request.method == "POST":
        # 1. HANDLE TEXT-BASED FIELDS
        fields = [
            'cult_hero_title', 'cult_hero_sub', 'cult_hero_tag',
            'cult_church_title', 'cult_old_lbl', 'cult_new_lbl',
            'cult_hist_title', 'cult_hist_text', 'cult_arch_title', 'cult_arch_text',
            'cult_patron_title', 'cult_patron_sub', 'cult_patron_text',
            'cult_mon_title', 'cult_mon_sub',
            'cult_m1_name', 'cult_m1_desc', 'cult_m1_pos',
            'cult_m2_name', 'cult_m2_desc', 'cult_m2_pos',
            'cult_m3_name', 'cult_m3_desc', 'cult_m3_pos'
        ]

        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))

        # 2. HANDLE IMAGE UPLOADS
        img_fields = ['cult_hero_bg', 'cult_old_img', 'cult_new_img', 'cult_patron_img',
                      'cult_m1_img', 'cult_m2_img', 'cult_m3_img']
        for field in img_fields:
            file = request.files.get(field + "_file")
            if file and file.filename != '':
                path = save_file(file)
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = path
                else: db.session.add(SiteContent(key=field, value=path))

        # 3. HANDLE DOWNLOADABLE FILE UPLOAD
        if "add_culture_file" in request.form:
            files = request.files.getlist("culture_docs")
            caption = request.form.get("file_caption")
            for file in files:
                if file and file.filename != '':
                    path = save_file(file)
                    new_media = HistoryMedia(
                        section_key='culture_downloads',
                        media_url=path,
                        media_type='file',
                        caption=caption
                    )
                    db.session.add(new_media)
            flash("Resources uploaded successfully.", "success")

        # 4. HANDLE FILE DELETION
        if "delete_culture_file" in request.form:
            media_id = request.form.get("media_id")
            media_item = HistoryMedia.query.get_or_404(media_id)
            db.session.delete(media_item)
            flash("File deleted.", "success")

        db.session.commit()
        flash("Culture Page updated successfully!", "success")
        return redirect(url_for("views.edit_culture"))

    # --- GET REQUEST ---
    defaults = {
        'cult_hero_title': 'Cultural Inventory', 
        'cult_hero_sub': 'The sacred sites...', 
        'cult_hero_tag': 'Preserving Heritage', 
        'cult_hero_bg': url_for('static', filename='images/municipal.jpg'),
        'cult_church_title': 'Most Holy Rosary Parish', 
        'cult_old_img': url_for('static', filename='images/church_old.jpg'), 
        'cult_old_lbl': 'The Old Church', 
        'cult_new_img': url_for('static', filename='images/church_new.jpg'), 
        'cult_new_lbl': 'The Modern Structure',
        'cult_hist_title': 'Historical Significance', 
        'cult_hist_text': 'The Parish stands as...', 
        'cult_arch_title': 'Architecture', 
        'cult_arch_text': 'Exterior details...',
        'cult_patron_img': url_for('static', filename='images/mama_mary.jpg'), 
        'cult_patron_title': 'Our Lady of the Most Holy Rosary', 
        'cult_patron_sub': '"The beloved patroness..."', 
        'cult_patron_text': 'The image...',
        'cult_mon_title': 'Historical Monuments', 
        'cult_mon_sub': 'Honoring Pillars',
        'cult_m1_name': 'Padre Vicente Garcia', 'cult_m1_desc': '...', 'cult_m1_img': '', 'cult_m1_pos': '50',
        'cult_m2_name': 'Hon. Graciano R. Recto', 'cult_m2_desc': '...', 'cult_m2_img': '', 'cult_m2_pos': '50',
        'cult_m3_name': 'Father Antonio', 'cult_m3_desc': '...', 'cult_m3_img': '', 'cult_m3_pos': '50'
    }
    
    content = {}
    for k, v in defaults.items(): 
        content[k] = get_content(k, v)
        
    # Fetch the downloadable files
    culture_files = HistoryMedia.query.filter_by(section_key='culture_downloads').all()
        
    return render_template("edit_cultural_inventory.html", content=content, culture_files=culture_files)

@views.route("/edit-festival", methods=["GET", "POST"])
@login_required
def edit_festival():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    
    if request.method == "POST":
        
        if "add_event" in request.form:
            file = request.files.get("ev_img")
            img_path = save_file(file) if file else None
            
            new_event = FestivalEvent(
                month=request.form.get("ev_month"), 
                day=request.form.get("ev_day"), 
                title=request.form.get("ev_title"), 
                location=request.form.get("ev_loc"), 
                description=request.form.get("ev_desc"),
                image_url=img_path # Save image
            )
            db.session.add(new_event)
            db.session.commit()
            flash("Activity added!", "success")
            return redirect(url_for("views.edit_festival"))
            
        if "edit_event" in request.form:
            ev = FestivalEvent.query.get(request.form.get("event_id"))
            if ev:
                ev.month = request.form.get("ev_month")
                ev.day = request.form.get("ev_day")
                ev.title = request.form.get("ev_title")
                ev.location = request.form.get("ev_loc")
                ev.description = request.form.get("ev_desc")
                
                file = request.files.get("ev_img")
                if file and file.filename != '':
                    ev.image_url = save_file(file)
                
                db.session.commit()
                flash("Activity updated!", "success")
            return redirect(url_for("views.edit_festival"))
            
        if "delete_event" in request.form:
            event = FestivalEvent.query.get(request.form.get("event_id"))
            if event:
                db.session.delete(event)
                db.session.commit()
            return redirect(url_for("views.edit_festival"))

        if "add_gal" in request.form:
            files = request.files.getlist("gal_img")
            caption = request.form.get("gal_cap")
            link_url = request.form.get("gal_link")
            
            image_added = False
            for file in files:
                if file and file.filename != '':
                    path = save_file(file)
                    if path:
                        new_gal = FestivalGalleryImage(
                            caption=caption,
                            link_url=link_url,
                            image_url=path
                        )
                        db.session.add(new_gal)
                        image_added = True
            
            if image_added:
                db.session.commit()
                flash("New gallery image(s) added successfully!", "success")
            else:
                flash("No images were selected for upload.", "error")
                
            return redirect(url_for("views.edit_festival"))

        if "edit_gal" in request.form:
            gal = FestivalGalleryImage.query.get(request.form.get("gal_id"))
            if gal:
                gal.caption = request.form.get("gal_cap")
                gal.link_url = request.form.get("gal_link")
                file = request.files.get("gal_img")
                if file and file.filename != '': gal.image_url = save_file(file)
                db.session.commit()
                flash("Gallery image updated!", "success")
            return redirect(url_for("views.edit_festival"))

        if "delete_gal" in request.form:
            gal = FestivalGalleryImage.query.get(request.form.get("gal_id"))
            if gal:
                db.session.delete(gal)
                db.session.commit()
            return redirect(url_for("views.edit_festival"))

        fields = [
            'fest_date_badge', 'fest_hero_title', 'fest_hero_sub',
            'fest_intro_title', 'fest_intro_text',
            'fest_c1_title', 'fest_c1_desc', 'fest_c2_title', 'fest_c2_desc', 'fest_c3_title', 'fest_c3_desc',
            'fest_legal_title', 'fest_legal_desc', 'fest_ord_text',
            'fest_prog_title', 'fest_prog_sub', 'fest_gal_title'
        ]
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
                
        img_fields = ['fest_hero_bg', 'fest_legal_img']
        for field in img_fields:
            file = request.files.get(field + "_file")
            if file and file.filename != '':
                path = save_file(file)
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = path
                else: db.session.add(SiteContent(key=field, value=path))
                
        db.session.commit()
        flash("Festival Page static content updated!", "success")
        return redirect(url_for("views.edit_festival"))

    events_list = FestivalEvent.query.all()
    gallery_list = FestivalGalleryImage.query.order_by(FestivalGalleryImage.id.desc()).all()
    
    defaults = {
        'fest_hero_bg': url_for('static', filename='images/festival_hero.jpg'), 'fest_date_badge': 'Every Dec 1', 'fest_hero_title': 'Kabakahan Festival', 'fest_hero_sub': 'Celebrating the Cattle Trading Capital',
        'fest_intro_title': 'The Spirit of the Festival', 'fest_intro_text': 'Annual cultural celebration...',
        'fest_c1_title': 'Culture', 'fest_c1_desc': 'Showcasing talent', 'fest_c2_title': 'Trade', 'fest_c2_desc': 'Boosting economy', 'fest_c3_title': 'Faith', 'fest_c3_desc': 'Thanksgiving',
        'fest_legal_title': 'Legal Basis', 'fest_legal_desc': 'Institutionalized by law...', 'fest_legal_img': url_for('static', filename='images/festival_parade.jpg'), 'fest_ord_text': 'WHEREAS...',
        'fest_prog_title': 'Program & Activities', 'fest_prog_sub': 'Highlights', 'fest_gal_title': 'Captured Moments'
    }
    content = {}
    for k, v in defaults.items(): content[k] = get_content(k, v)
    
    return render_template("edit_festival.html", content=content, events=events_list, gallery=gallery_list)

@views.route("/edit-food", methods=["GET", "POST"])
@login_required
def edit_food():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    
    if request.method == "POST":
        
        if "add_dish" in request.form:
            new_dish = FoodDish(
                name=request.form.get("dish_name"),
                tagline=request.form.get("dish_tagline"),
                description=request.form.get("dish_desc"),
                link_url=request.form.get("dish_link"),
                image_url=save_file(request.files.get("dish_img")) if request.files.get("dish_img") else None
            )
            db.session.add(new_dish)
            db.session.commit()
            flash("Dish added successfully!", "success")
            return redirect(url_for("views.edit_food"))

        if "edit_dish" in request.form:
            dish = FoodDish.query.get(request.form.get("dish_id"))
            if dish:
                dish.name = request.form.get("dish_name")
                dish.tagline = request.form.get("dish_tagline")
                dish.description = request.form.get("dish_desc")
                dish.link_url = request.form.get("dish_link")
                file = request.files.get("dish_img")
                if file and file.filename != '': dish.image_url = save_file(file)
                db.session.commit()
                flash("Dish updated!", "success")
            return redirect(url_for("views.edit_food"))

        if "delete_dish" in request.form:
            dish = FoodDish.query.get(request.form.get("dish_id"))
            if dish:
                db.session.delete(dish)
                db.session.commit()
            return redirect(url_for("views.edit_food"))

        if "add_sweet" in request.form:
            new_sweet = SweetTreat(
                name=request.form.get("sweet_name"),
                description=request.form.get("sweet_desc"),
                link_url=request.form.get("sweet_link"),
                image_url=save_file(request.files.get("sweet_img")) if request.files.get("sweet_img") else None
            )
            db.session.add(new_sweet)
            db.session.commit()
            flash("Sweet Treat added!", "success")
            return redirect(url_for("views.edit_food"))

        if "edit_sweet" in request.form:
            sweet = SweetTreat.query.get(request.form.get("sweet_id"))
            if sweet:
                sweet.name = request.form.get("sweet_name")
                sweet.description = request.form.get("sweet_desc")
                sweet.link_url = request.form.get("sweet_link")
                file = request.files.get("sweet_img")
                if file and file.filename != '': sweet.image_url = save_file(file)
                db.session.commit()
                flash("Sweet Treat updated!", "success")
            return redirect(url_for("views.edit_food"))

        if "delete_sweet" in request.form:
            sweet = SweetTreat.query.get(request.form.get("sweet_id"))
            if sweet:
                db.session.delete(sweet)
                db.session.commit()
            return redirect(url_for("views.edit_food"))

        fields = ['food_hero_title', 'food_hero_sub', 'food_hero_desc', 'food_s3_title', 'food_s3_desc']
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
                
        file = request.files.get("food_hero_bg_file")
        if file and file.filename != '':
            path = save_file(file)
            existing = SiteContent.query.filter_by(key='food_hero_bg').first()
            if existing: existing.value = path
            else: db.session.add(SiteContent(key='food_hero_bg', value=path))
                
        db.session.commit()
        flash("Food Page static content updated!", "success")
        return redirect(url_for("views.edit_food"))

    defaults = {
        'food_hero_title': 'Gastronomic Delights', 
        'food_hero_sub': 'Taste of Padre Garcia', 
        'food_hero_desc': 'Discover the rich, savory flavors...', 
        'food_hero_bg': url_for('static', filename='images/food_hero.jpg'),
        'food_s3_title': 'Sweets & Pasalubong', 
        'food_s3_desc': 'Take home a piece of Padre Garcia...'
    }
    content = {}
    for k, v in defaults.items(): content[k] = get_content(k, v)
    
    dishes = FoodDish.query.order_by(FoodDish.id.desc()).all()
    sweets = SweetTreat.query.order_by(SweetTreat.id.desc()).all()
    
    return render_template("edit_food.html", content=content, dishes=dishes, sweets=sweets)

@views.route("/edit-contact", methods=["GET", "POST"])
@login_required
def edit_contact():
    if not current_user.is_admin: return redirect(url_for("views.home"))
    if request.method == "POST":
        fields = [
            'contact_hero_title', 'contact_hero_sub',
            'contact_card_addr_title', 'contact_card_addr_text',
            'contact_card_phone_title', 'contact_phone_main', 'contact_phone_alt',
            'contact_card_email_title', 'contact_email_main', 'contact_email_alt',
            'contact_form_title', 'contact_map_url'
        ]
        for field in fields:
            val = request.form.get(field)
            if val is not None:
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = val
                else: db.session.add(SiteContent(key=field, value=val))
        img_fields = ['contact_hero_bg']
        for field in img_fields:
            file = request.files.get(field + "_file")
            if file and file.filename != '':
                path = save_file(file)
                existing = SiteContent.query.filter_by(key=field).first()
                if existing: existing.value = path
                else: db.session.add(SiteContent(key=field, value=path))
        db.session.commit()
        flash("Contact Page updated!", "success")
        return redirect(url_for("views.edit_contact"))
    defaults = {
        'contact_hero_title': 'Get in Touch', 'contact_hero_sub': "We'd love to hear from you", 'contact_hero_bg': url_for('static', filename='images/municipal.jpg'),
        'contact_card_addr_title': 'Visit Us', 'contact_card_addr_text': '2nd Flr. LAM Bldg, Poblacion...',
        'contact_card_phone_title': 'Call Us', 'contact_phone_main': '(043) 515-9209', 'contact_phone_alt': '(043) 515-7424',
        'contact_card_email_title': 'Email Us', 'contact_email_main': 'tourism@padregarcia.gov.ph', 'contact_email_alt': 'info@padregarcia.gov.ph',
        'contact_form_title': 'Send us a Message', 'contact_map_url': 'https://www.google.com/maps/embed?pb=...'
    }
    content = {}
    for k, v in defaults.items(): content[k] = get_content(k, v)
    return render_template("edit_contact.html", content=content)