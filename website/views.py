import json
import csv
import io
import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, Response, send_file
import shutil
from flask_login import login_required, current_user
from .models import User, ContactMessage, Booking, PortfolioItem, ServicePackage, SiteSetting, SocialLink, QuickLink, InventoryItem
from . import db
from datetime import datetime
from calendar import month_abbr
from werkzeug.utils import secure_filename 
from flask import current_app
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
from werkzeug.security import generate_password_hash 
from datetime import timedelta
import requests

# SMS CONFIGURATION
TEXTBEE_API_KEY = "f8346679-4874-482d-8a90-179e1c918cfe"
TEXTBEE_DEVICE_ID = "695bd01ed6a8a5e2477437c8"
BRAND_NAME = "Wandershots" 
DEFAULT_COUNTRY_CODE = "63"

views = Blueprint('views', __name__)

UPLOAD_FOLDER = 'website/static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov', 'webm'}

def format_phone(phone):
    """Ensures phone number starts with 63 and has no spaces/symbols"""
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if clean_phone.startswith('0'):
        clean_phone = DEFAULT_COUNTRY_CODE + clean_phone[1:]
    elif not clean_phone.startswith(DEFAULT_COUNTRY_CODE):
        clean_phone = DEFAULT_COUNTRY_CODE + clean_phone
    return clean_phone

def send_sms(phone, message):
    """Triggers SMS via TextBee API with corrected recipient format"""
    if not phone:
        return
    
    url = f"https://api.textbee.dev/api/v1/gateway/devices/{TEXTBEE_DEVICE_ID}/send-sms"
    
    # THE FIX: TextBee expects "recipients" as a LIST [number], not "receiver" as a string
    payload = {
        "recipients": [format_phone(phone)], 
        "message": f"{message}\n\n- {BRAND_NAME}"
    }
    
    headers = { "x-api-key": TEXTBEE_API_KEY }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code in [200, 201]:
            print(f"📱 SMS sent to {phone} successfully!")
        else:
            # This will help us see exactly what's wrong if it fails again
            print(f"❌ SMS Failed: {response.text} for number {format_phone(phone)}")
    except Exception as e:
        print(f"📱 SMS Exception: {e}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_setting(key, default_value=""):
    setting = SiteSetting.query.filter_by(setting_key=key).first()
    return setting.setting_value if setting else default_value

def set_setting(key, value):
    setting = SiteSetting.query.filter_by(setting_key=key).first()
    if setting:
        setting.setting_value = value
    else:
        new_setting = SiteSetting(setting_key=key, setting_value=value)
        db.session.add(new_setting)

def get_image_url(filename, default_url):
    if not filename:
        return default_url
    if filename.startswith('http://') or filename.startswith('https://'):
        return filename
    return url_for('static', filename='images/' + filename)

# --- CONTACT INQUIRY EMAIL LOGIC ---

def send_contact_message_email(app, name, email, message):
    with app.app_context():
        SMTP_USER = "enemyslayer0909@gmail.com" 
        SMTP_PASS = "unma ljgl hmhl pvhv" 
        recipient_email = get_setting('notification_recipient_email', SMTP_USER)
        admin_phone = get_setting('admin_phone_number', '')

        # --- EMAIL CONTENT ---
        subject = f"New Website Inquiry from {name}"
        body = f"""You have a new message from the contact form!

    SENDER DETAILS:
    Name: {name}
    Email: {email}

    MESSAGE:
    {message}

    --------------------------------------------------
    Reply directly to this email to contact the user.
    """
        msg = MIMEMultipart(); msg['From'] = f"Wandershots Website <{SMTP_USER}>"; msg['To'] = recipient_email
        msg['Subject'] = subject; msg.add_header('reply-to', email); msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
            server.login(SMTP_USER, SMTP_PASS); server.send_message(msg); server.quit()
        except Exception: pass

        # --- SMS CONTENT (Admin) ---
        if admin_phone:
            sms_text = f"New Inquiry: {name}\nMsg: {message[:60]}..."
            send_sms(admin_phone, sms_text)

def async_send_contact_email(*args):
    app = current_app._get_current_object()
    thread = threading.Thread(target=send_contact_message_email, args=(app, *args))
    thread.start()

def send_client_confirmation_email(app, recipient_email, recipient_phone, name, service, date, time, location):
    with app.app_context():
        SMTP_USER = "enemyslayer0909@gmail.com" 
        SMTP_PASS = "unma ljgl hmhl pvhv" 
        business_email = get_setting('notification_recipient_email', SMTP_USER)

        # --- EMAIL CONTENT ---
        subject = f"Booking Confirmed! - {service}"
        body = f"""Hi {name},

        Great news! Your booking request for {service} has been officially confirmed and scheduled.

        EVENT DETAILS:
        Service: {service}
        Date: {date}
        Time: {time}
        Location: {location or 'In Studio'}

        We look forward to capturing your special moments! If you have any questions, please reply directly to this email.

        Best regards,
        Wandershots Studios Team
        """
        msg = MIMEMultipart(); msg['From'] = f"Wandershots Studios <{business_email}>"; msg['To'] = recipient_email
        msg['Subject'] = subject; msg.add_header('reply-to', business_email); msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
            server.login(SMTP_USER, SMTP_PASS); server.send_message(msg); server.quit()
        except Exception: pass

        # --- SMS CONTENT (Client) ---
        sms_text = f"Hi {name}, Great news! Your booking for {service} on {date} is officially confirmed and scheduled. See you soon!"
        send_sms(recipient_phone, sms_text)

def send_event_reminder_email(app, booking):
    with app.app_context():
        SMTP_USER = "enemyslayer0909@gmail.com" 
        SMTP_PASS = "unma ljgl hmhl pvhv" 
        business_email = get_setting('notification_recipient_email', SMTP_USER)
        admin_phone = get_setting('admin_phone_number', '')

        # --- EMAIL CONTENT (Client) ---
        subject = f"Reminder: Your session is coming up! - {booking.service_type}"
        body = f"""Hi {booking.customer_name},

        This is a friendly reminder that your {booking.service_type} session is scheduled for tomorrow!

        EVENT DETAILS:
        Service: {booking.service_type}
        Date: {booking.date}
        Time: {booking.time}
        Location: {booking.location or 'In Studio'}

        We look forward to seeing you!
        
        Best regards,
        Wandershots Studios Team
        """
        msg = MIMEMultipart(); msg['From'] = f"Wandershots Studios <{business_email}>"; msg['To'] = booking.customer_email
        msg['Subject'] = subject; msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
            server.login(SMTP_USER, SMTP_PASS); server.send_message(msg); server.quit()
        except Exception: pass

        # --- SMS CONTENT (Client) ---
        send_sms(booking.customer_phone, f"Hi {booking.customer_name}, just a reminder that your session for {booking.service_type} is scheduled for tomorrow at {booking.time}!")

        # --- SMS CONTENT (Admin) ---
        if admin_phone:
            send_sms(admin_phone, f"Admin Reminder: Booking with {booking.customer_name} is scheduled for tomorrow at {booking.time}.")

        # Update DB
        booking.reminder_sent = True
        db.session.commit()

# --- THE BACKGROUND TASK ---
def check_upcoming_events(app):
    with app.app_context():
        current_time = datetime.now()
        
        # 1. Get the admin's setting for hours (default to 24 if not set)
        try:
            hours_threshold = int(get_setting('reminder_hours_before', '24'))
        except ValueError:
            hours_threshold = 24

        # 2. Get scheduled bookings that haven't received a reminder
        bookings = Booking.query.filter_by(status='scheduled', reminder_sent=False).all()

        for b in bookings:
            try:
                # Combine b.date (YYYY-MM-DD) and b.time (HH:MM) into a datetime object
                event_datetime = datetime.strptime(f"{b.date} {b.time}", '%Y-%m-%d %H:%M')
                
                # Calculate the difference
                time_diff = event_datetime - current_time
                hours_until_event = time_diff.total_seconds() / 3600

                # 3. If the event is within the threshold (but still in the future)
                if 0 < hours_until_event <= hours_threshold:
                    send_event_reminder_email(app, b)
            except Exception as e:
                print(f"Error processing reminder for booking {b.id}: {e}")


def async_send_client_email(*args):
    app = current_app._get_current_object()
    thread = threading.Thread(target=send_client_confirmation_email, args=(app, *args))
    thread.start()

def send_new_booking_email(app, name, email, phone, service, package, date, time, location, notes):
    with app.app_context():
        SMTP_USER = "enemyslayer0909@gmail.com" 
        SMTP_PASS = "unma ljgl hmhl pvhv" 
        recipient_email = get_setting('notification_recipient_email', SMTP_USER)
        admin_phone = get_setting('admin_phone_number', '')

        # --- EMAIL CONTENT ---
        subject = f"New Booking Request: {service} - {name}"
        body = f"""You have a new booking request from your website!

    CUSTOMER DETAILS:
    Name: {name}
    Email: {email}
    Phone: {phone}

    EVENT DETAILS:
    Service: {service}
    Package: {package or 'None'}
    Date: {date}
    Time: {time}
    Location: {location or 'In Studio'}

    Notes:
    {notes or 'None'}
    """
        msg = MIMEMultipart(); msg['From'] = f"Wandershots System <{SMTP_USER}>"; msg['To'] = recipient_email
        msg['Subject'] = subject; msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
            server.login(SMTP_USER, SMTP_PASS); server.send_message(msg); server.quit()
        except Exception: pass

        # --- SMS CONTENT (Admin) ---
        if admin_phone:
            sms_text = f"New Booking: {name}\nService: {service}\nDate: {date} @ {time}\nLoc: {location[:30]}..."
            send_sms(admin_phone, sms_text)

def async_send_email(*args):
    """
    SANDS 10 ITEMS TOTAL:
    The app object + the 9 booking details
    """
    # 1. Get the real app object
    app = current_app._get_current_object()
    
    # 2. Start thread passing (app, arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9)
    thread = threading.Thread(target=send_new_booking_email, args=(app, *args))
    thread.start()

def post_portfolio_to_facebook(app, portfolio_id):
    with app.app_context():
        item = PortfolioItem.query.get(portfolio_id)
        page_id = get_setting('fb_page_id')
        token = get_setting('fb_access_token')
        
        if not item or not page_id or not token: return

        # 1. Collect all media files
        files_to_upload = [item.image_filename, item.image_filename_2, item.image_filename_3, item.image_filename_4]
        media_ids = []
        
        caption = f"✨ {item.title}\n📂 Category: {item.category}\n\n{item.description}"

        for filename in files_to_upload:
            if not filename: continue
            
            path = os.path.join(current_app.root_path, 'static/images', filename)
            if not os.path.exists(path): continue

            is_video = filename.lower().endswith(('.mp4', '.mov', '.webm'))
            
            try:
                if is_video:
                    # Upload Video (Unpublished)
                    url = f"https://graph-video.facebook.com/v19.0/{page_id}/videos"
                    with open(path, 'rb') as f:
                        r = requests.post(url, data={'published': 'false', 'access_token': token}, files={'source': f})
                else:
                    # Upload Photo (Unpublished)
                    url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
                    with open(path, 'rb') as f:
                        r = requests.post(url, data={'published': 'false', 'access_token': token}, files={'source': f})
                
                res = r.json()
                if 'id' in res:
                    # Add to the list for the final post
                    media_ids.append(res['id'])
            except Exception as e:
                print(f"Media upload error: {e}")

        # 2. Create the final "Multi-Media" Feed Post
        if media_ids:
            feed_url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            # Format media IDs for FB
            attached_media = json.dumps([{'media_fbid': id} for id in media_ids])
            
            r = requests.post(feed_url, data={
                'message': caption,
                'attached_media': attached_media,
                'access_token': token
            })
            
            res = r.json()
            if 'id' in res:
                item.fb_post_id = res['id']
                db.session.commit()
                print(f"✅ Full Multi-Media Post Created: {res['id']}")

def delete_facebook_post(app, post_id):
    """Deletes a post from FB Page - Context Aware"""
    with app.app_context():
        token = get_setting('fb_access_token')
        if post_id and token:
            try:
                url = f"https://graph.facebook.com/v19.0/{post_id}"
                response = requests.delete(url, data={'access_token': token})
                if response.status_code == 200:
                    print(f"✅ Successfully deleted FB post: {post_id}")
                else:
                    print(f"❌ FB Delete Error: {response.text}")
            except Exception as e:
                print(f"❌ FB Delete Exception: {e}")




@views.route('/')
def home():
    # Fetch content from database, fallback to defaults if empty
    settings = {
        # Hero Section
        'hero_pre': get_setting('home_hero_pre', 'TIMELESS STYLE'),
        'hero_title': get_setting('home_hero_title', 'Timeless<br><em class="font-light italic">Elegance</em><br>in Every Frame.'),
        'hero_desc': get_setting('home_hero_desc', "Capturing life's most precious moments with artistic vision and technical excellence. Every photograph tells a story worth preserving for generations."),
        'hero_bg_img': get_image_url(get_setting('home_hero_bg_img'), 'https://readdy.ai/api/search-image?query=elegant%20photography%20studio%20with%20soft%20natural%20lighting%2C%20minimal%20modern%20interior%20design%2C%20professional%20camera%20equipment%2C%20clean%20white%20walls%2C%20large%20windows%20with%20diffused%20sunlight%2C%20sophisticated%20atmosphere%2C%20high-end%20photography%20workspace&width=1920&height=1080&seq=hero-bg-001&orientation=landscape'),
        'hero_portrait_img': get_image_url(get_setting('home_hero_portrait_img'), 'https://readdy.ai/api/search-image?query=professional%20portrait%20photography%20of%20elegant%20woman%20with%20natural%20lighting%2C%20soft%20shadows%2C%20timeless%20beauty%2C%20classic%20composition%2C%20high-end%20fashion%20photography%20style%2C%20sophisticated%20atmosphere%2C%20artistic%20black%20and%20white%20tones&width=600&height=750&seq=hero-portrait-001&orientation=portrait'),
        
        # Expertise Section
        'expertise_title': get_setting('home_expertise_title', 'Our Expertise'),
        'exp1_title': get_setting('home_exp1_title', 'Studio Portraits'),
        'exp1_desc': get_setting('home_exp1_desc', 'Professional studio sessions with controlled lighting and premium backdrops for timeless portrait photography that captures your unique personality.'),
        'exp2_title': get_setting('home_exp2_title', 'Event Coverage'),
        'exp2_desc': get_setting('home_exp2_desc', 'Comprehensive wedding and event photography services that document every precious moment with artistic flair and professional discretion.'),
        'exp3_title': get_setting('home_exp3_title', 'Luxury Photobooth'),
        'exp3_desc': get_setting('home_exp3_desc', 'Premium on-site studio booths with magnetic prints, custom elegant layouts, and flawless professional lighting setups.'),

        # About Preview Section
        'about_pre': get_setting('home_about_pre', 'OUR APPROACH'),
        'about_title': get_setting('home_about_title', 'Crafting Moments,<br>Building <em class="italic">Legacies</em>.'),
        'about_p1': get_setting('home_about_p1', 'With over a decade of experience in fine art photography, we believe that every image should tell a story that transcends time. Our approach combines classical composition techniques with modern artistic vision.'),
        'about_p2': get_setting('home_about_p2', 'From intimate portraits to grand celebrations, we focus on capturing the authentic emotions and genuine connections that make each moment unique and meaningful for generations to come.'),
        'about_img': get_image_url(get_setting('home_about_img'), 'https://readdy.ai/api/search-image?query=professional%20photography%20workspace%20with%20vintage%20cameras%2C%20artistic%20lighting%20equipment%2C%20film%20rolls%2C%20elegant%20desk%20setup%2C%20creative%20studio%20environment%2C%20warm%20natural%20lighting%2C%20sophisticated%20photographer%20tools%20and%20equipment&width=600&height=700&seq=workspace-001&orientation=portrait'),
        
        
        # Portfolio Preview Section
        'portfolio_title': get_setting('home_portfolio_title', 'Featured Projects'),
        
        'port1_img': get_image_url(get_setting('home_port1_img'), 'https://readdy.ai/api/search-image?query=elegant%20wedding...'),
        'port1_title': get_setting('home_port1_title', 'Romantic Wedding'),
        'port1_sub': get_setting('home_port1_sub', 'Outdoor Ceremony'),
        'port1_link': get_setting('home_port1_link', '#'), # <--- ADD THIS
        
        'port2_img': get_image_url(get_setting('home_port2_img'), 'https://readdy.ai/api/search-image?query=professional%20family...'),
        'port2_title': get_setting('home_port2_title', 'Family Legacy'),
        'port2_sub': get_setting('home_port2_sub', 'Studio Session'),
        'port2_link': get_setting('home_port2_link', '#'), # <--- ADD THIS
        
        'port3_img': get_image_url(get_setting('home_port3_img'), 'https://readdy.ai/api/search-image?query=artistic%20lifestyle...'),
        'port3_title': get_setting('home_port3_title', 'Lifestyle Session'),
        'port3_sub': get_setting('home_port3_sub', 'Natural Setting'),
        'port3_link': get_setting('home_port3_link', '#'), # <--- ADD THIS

        # Call to Action
        'cta_title': get_setting('home_cta_title', "Let's create something beautiful."),
        'cta_desc': get_setting('home_cta_desc', "Ready to capture your story? Our calendar fills up quickly for the upcoming season. We'd love to discuss your vision and create timeless photographs that celebrate your most precious moments.")
    }
    return render_template("index.html", user=current_user, page='home', settings=settings)
# ==========================================

@views.route('/admin/cms/home', methods=['GET', 'POST'])
@login_required
def admin_cms_home():
    # Define text fields
    text_keys = [
        'home_hero_pre', 'home_hero_title', 'home_hero_desc',
        'home_expertise_title', 'home_exp1_title', 'home_exp1_desc', 'home_exp2_title', 'home_exp2_desc', 'home_exp3_title', 'home_exp3_desc',
        'home_about_pre', 'home_about_title', 'home_about_p1', 'home_about_p2',
        'home_portfolio_title', 'home_port1_title', 'home_port1_sub', 'home_port1_link', # <-- Added Link
        'home_port2_title', 'home_port2_sub', 'home_port2_link', # <-- Added Link
        'home_port3_title', 'home_port3_sub', 'home_port3_link', # <-- Added Link
        'home_cta_title', 'home_cta_desc'
    ]
    # Define image file fields
    image_keys = [
        'home_hero_bg_img', 'home_hero_portrait_img', 'home_about_img',
        'home_port1_img', 'home_port2_img', 'home_port3_img'
    ]

    if request.method == 'POST':
        # 1. Save Text Fields
        for key in text_keys:
            set_setting(key, request.form.get(key, ''))
            
        # 2. Save Uploaded Images
        for key in image_keys:
            file = request.files.get(key)
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Ensure directory exists
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                set_setting(key, filename) # Save filename to database
            
            # If user pasted an external URL instead of uploading a file
            elif request.form.get(f"{key}_url"):
                set_setting(key, request.form.get(f"{key}_url"))
            
        db.session.commit()
        flash('Homepage content updated successfully!', category='success')
        return redirect(url_for('views.admin_cms_home'))

    # Load current settings to populate the form
    settings = {}
    for key in text_keys + image_keys:
        # Default empty string, actual defaults are handled on the frontend/home route
        settings[key] = get_setting(key, "") 
    
    counts = get_sidebar_counts()
    return render_template("admin_cms_home.html", user=current_user, page='dashboard', settings=settings, **counts)

@views.route('/admin/cms/about', methods=['GET', 'POST'])
@login_required
def admin_cms_about():
    # Define fields
    text_keys = [
        'about_header_pre', 'about_header_title', 'about_header_desc',
        'about_story_title', 'about_story_text',
        'about_stat1_num', 'about_stat1_label',
        'about_stat2_num', 'about_stat2_label',
        'about_stat3_num', 'about_stat3_label'
    ]
    image_keys = ['about_main_img']

    if request.method == 'POST':
        # 1. Save Text Fields
        for key in text_keys:
            set_setting(key, request.form.get(key, ''))
            
        # 2. Save Uploaded Images
        for key in image_keys:
            file = request.files.get(key)
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                set_setting(key, filename)
            elif request.form.get(f"{key}_url"):
                set_setting(key, request.form.get(f"{key}_url"))
            
        db.session.commit()
        flash('About page content updated successfully!', category='success')
        return redirect(url_for('views.admin_cms_about'))

    # Load current settings
    settings = {}
    for key in text_keys + image_keys:
        settings[key] = get_setting(key, "") 
    
    counts = get_sidebar_counts()
    return render_template("admin_cms_about.html", user=current_user, page='dashboard', settings=settings, **counts)

@views.route('/about')
def about():
    settings = {
        'header_pre': get_setting('about_header_pre', 'THE STORY'),
        'header_title': get_setting('about_header_title', 'About <em class="italic">Wandershots</em>'),
        'header_desc': get_setting('about_header_desc', 'The vision, passion, and artistic dedication behind the lens.'),
        
        'story_title': get_setting('about_story_title', 'A Decade of<br><em class="italic text-gray-600">Craftsmanship</em><br>and Dedication.'),
        'story_text': get_setting('about_story_text', 'For over ten years, Wandershots Studios has been dedicated to capturing moments that transcend time. Our journey has taken us through countless stories, each one a testament to our passion for elegant and authentic visual narratives. We specialize in bringing out the genuine emotion and sophisticated beauty in every subject we photograph.'),
        
        'stat1_num': get_setting('about_stat1_num', '500+'),
        'stat1_label': get_setting('about_stat1_label', 'Clients'),
        'stat2_num': get_setting('about_stat2_num', '150+'),
        'stat2_label': get_setting('about_stat2_label', 'Events'),
        'stat3_num': get_setting('about_stat3_num', '25'),
        'stat3_label': get_setting('about_stat3_label', 'Awards'),
        
        'main_img': get_image_url(get_setting('about_main_img'), 'https://readdy.ai/api/search-image?query=Professional%20female%20photographer%20with%20camera%20in%20modern%20studio%20setting%20black%20and%20white&width=600&height=800&seq=about-main')
    }
    return render_template("about.html", user=current_user, page='about', settings=settings)

@views.route('/works')
def works():
    # Fetch all portfolio items for the works page
    portfolio_items = PortfolioItem.query.order_by(PortfolioItem.created_at.desc()).all()
    return render_template("works.html", user=current_user, page='works', portfolio_items=portfolio_items)

@views.route('/booking-success')
def booking_success():
    name = request.args.get('name', 'Guest')
    return render_template("booking_success.html", user=current_user, page='book', name=name)

@views.route('/book', methods=['GET', 'POST'])
def book():
    packages = ServicePackage.query.order_by(ServicePackage.price).all()
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        service_type = request.form.get('service_type')
        
        location = request.form.get('location') 
        map_url = request.form.get('map_url')
        package_selected = request.form.get('package_selected') 
        
        date = request.form.get('date')
        time = request.form.get('time')
        notes = request.form.get('notes')

        if not name or not email or not phone:
            flash('Please provide your name, email, and contact number.', category='error')
        elif not service_type:
            flash('Please select a service type.', category='error')
        elif service_type == 'Photobooth' and not package_selected:
            flash('Please select a Photobooth package.', category='error')
        elif not date or not time:
            flash('Please select a date and time.', category='error')
        else:
            new_booking = Booking(
                customer_name=name,
                customer_email=email,
                customer_phone=phone, 
                service_type=service_type,
                package_selected=package_selected, 
                location=location,
                map_url=map_url,
                date=date,
                time=time,
                notes=notes,
                status='pending',
                is_archived=False 
            )
            db.session.add(new_booking)
            db.session.commit()
            
            # TRIGGER EMAIL NOTIFICATION IN BACKGROUND
            async_send_email(name, email, phone, service_type, package_selected, date, time, location, notes)
            
            # REDIRECT TO SUCCESS PAGE INSTEAD OF HOME
            return redirect(url_for('views.booking_success', name=name))

    return render_template("booking.html", user=current_user, page='book', packages=packages)

@views.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')

        if not name or len(name) < 2:
            flash('Name is too short!', category='error')
        elif not message or len(message) < 5:
            flash('Message is too short!', category='error')
        else:
            # 1. Save to Database
            new_msg = ContactMessage(name=name, email=email, message=message, is_archived=False)
            db.session.add(new_msg)
            db.session.commit()
            
            # 2. TRIGGER EMAIL ALERT
            async_send_contact_email(name, email, message)
            
            flash('Message sent successfully! Our team will get back to you soon.', category='success')
            return redirect(url_for('views.contact'))
    
    
    default_map_embed = '<iframe src="https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3022.617326224328!2d-73.98801202450824!3d40.74844087139158!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x89c259a9b3117469%3A0xd134e199a405a163!2sEmpire%20State%20Building!5e0!3m2!1sen!2sph!4v1715494123456!5m2!1sen!2sph" width="600" height="450" style="border:0;" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>'
    
    settings = {
        'title': get_setting('contact_header_title', 'Get In Touch'),
        'desc': get_setting('contact_header_desc', 'Have a question? Fill out the form or use the details below to reach us.'),
        'address': get_setting('contact_address', '123 Creative District\nNew York, NY 10001'),
        'phone': get_setting('contact_phone', '+1 (555) 123-4567\nMon-Fri, 9am - 6pm'),
        'email': get_setting('contact_email', 'hello@wandershots.com\nSupport & Inquiries'),
        'map_embed_url': get_setting('contact_map_embed_url', default_map_embed)
    }
    return render_template("contact.html", user=current_user, page='contact', settings=settings)

@views.route('/admin/cms/contact', methods=['GET', 'POST'])
@login_required
def admin_cms_contact():
    text_keys = [
        'contact_header_title', 'contact_header_desc',
        'contact_address', 'contact_phone', 'contact_email',
        'contact_map_embed_url'  # This is the key for the Google Maps HTML
    ]

    if request.method == 'POST':
        for key in text_keys:
            # Use request.form.get() to save the HTML code as is from the textarea
            set_setting(key, request.form.get(key, ''))
            
        db.session.commit()
        flash('Contact info updated successfully!', category='success')
        return redirect(url_for('views.admin_cms_contact'))

    # Load current settings to populate the form fields
    settings = {}
    for key in text_keys:
        settings[key] = get_setting(key, "") 
    
    counts = get_sidebar_counts()
    return render_template("admin_cms_contact.html", user=current_user, page='dashboard', settings=settings, **counts)

@views.route('/admin/cms/header', methods=['GET', 'POST'])
@login_required
def admin_cms_header():
    text_keys = ['header_logo_type', 'header_logo_text', 'header_cta_text', 'header_cta_link']
    image_keys = ['header_logo_image']

    if request.method == 'POST':
        # Save text fields
        for key in text_keys:
            set_setting(key, request.form.get(key, ''))
            
        # Save uploaded image
        for key in image_keys:
            file = request.files.get(key)
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                set_setting(key, filename)
            elif request.form.get(f"{key}_url"):
                set_setting(key, request.form.get(f"{key}_url"))
            
        db.session.commit()
        flash('Header & Logo settings updated successfully!', category='success')
        return redirect(url_for('views.admin_cms_header'))

    settings = {}
    for key in text_keys + image_keys:
        settings[key] = get_setting(key, "") 
        
    counts = get_sidebar_counts()
    return render_template("admin_cms_header.html", user=current_user, page='dashboard', settings=settings, **counts)

@views.route('/admin/cms/footer', methods=['GET', 'POST'])
@login_required
def admin_cms_footer():
    # Only keep copyright here, as social and quicklinks are now dynamic models
    text_keys = [
        'footer_desc', # Kept for general footer description
        'footer_avail_1', 'footer_avail_2', 'footer_avail_3', 'footer_avail_4',
        'footer_contact_phone', 'footer_contact_email', 'footer_contact_address',
        'footer_copyright'
    ]

    if request.method == 'POST':
        for key in text_keys:
            set_setting(key, request.form.get(key, ''))
            
        db.session.commit()
        flash('Footer info updated successfully!', category='success')
        return redirect(url_for('views.admin_cms_footer'))

    settings = {}
    for key in text_keys:
        settings[key] = get_setting(key, "") 
    
    counts = get_sidebar_counts()
    return render_template("admin_cms_footer.html", user=current_user, page='dashboard', settings=settings, **counts)

# --- HELPER FOR SOCIAL ICONS ---
def get_social_icon_class(platform_name):
    platform_name_lower = platform_name.lower()
    if "facebook" in platform_name_lower:
        return "ri-facebook-fill"
    elif "instagram" in platform_name_lower:
        return "ri-instagram-line"
    elif "twitter" in platform_name_lower or "x.com" in platform_name_lower or "x" == platform_name_lower:
        return "ri-twitter-x-line"
    elif "youtube" in platform_name_lower:
        return "ri-youtube-fill"
    elif "linkedin" in platform_name_lower:
        return "ri-linkedin-fill"
    elif "tiktok" in platform_name_lower:
        return "ri-tiktok-fill"
    elif "pinterest" in platform_name_lower:
        return "ri-pinterest-fill"
    elif "whatsapp" in platform_name_lower:
        return "ri-whatsapp-fill"
    else:
        return "ri-share-line" 

@views.context_processor
def inject_global_settings():
    """Injects global settings (Header/Footer, Dynamic Links) into all templates"""
    
    # Fetch dynamic social links
    social_links = SocialLink.query.order_by(SocialLink.order).all()
    # Fetch dynamic quick links
    quick_links = QuickLink.query.order_by(QuickLink.order).all()

    return dict(

        user=current_user,
        get_setting=get_setting, 
        # Header Settings
        header_logo_type=get_setting('header_logo_type', 'text'),
        header_logo_image=get_image_url(get_setting('header_logo_image'), ''),
        header_logo_text=get_setting('header_logo_text', 'Wandershots'),
        header_cta_text=get_setting('header_cta_text', 'BOOK SESSION'),
        header_cta_link=get_setting('header_cta_link', '/book'),
        
        # Footer Settings
        footer_desc=get_setting('footer_desc', "Creating timeless photography that captures the essence of life's most precious moments with artistic excellence."),
        footer_avail_1=get_setting('footer_avail_1', 'Monday - Friday: 9AM - 6PM'),
        footer_avail_2=get_setting('footer_avail_2', 'Saturday: 10AM - 4PM'),
        footer_avail_3=get_setting('footer_avail_3', 'Sunday: By Appointment'),
        footer_avail_4=get_setting('footer_avail_4', 'Emergency: 24/7 Available'),
        footer_contact_phone=get_setting('footer_contact_phone', '+1 (555) 123-4567'),
        footer_contact_email=get_setting('footer_contact_email', 'hello@wandershots.com'),
        footer_contact_address=get_setting('footer_contact_address', 'Creative District, NY'),
        footer_copyright=get_setting('footer_copyright', '© 2024 Wandershots Studios. All rights reserved. | Privacy Policy | Terms of Service'),

        # NEW: Dynamic social and quick links for the footer
        social_links=social_links,
        quick_links=quick_links
    )

@views.route('/admin/manage_links', methods=['GET'])
@login_required
def admin_manage_links():
    social_links = SocialLink.query.order_by(SocialLink.order).all()
    quick_links = QuickLink.query.order_by(QuickLink.order).all()
    counts = get_sidebar_counts()
    return render_template("admin_manage_links.html", user=current_user, page='dashboard', 
                           social_links=social_links, quick_links=quick_links, **counts)


@views.route('/admin/add_social_link', methods=['POST'])
@login_required
def admin_add_social_link():
    platform = request.form.get('platform')
    url = request.form.get('url')

    if not platform or not url:
        flash('Platform and URL are required for social link.', category='error')
        return redirect(url_for('views.admin_manage_links'))
    
    # Check if platform already exists
    existing_link = SocialLink.query.filter_by(platform=platform).first()
    if existing_link:
        flash(f'A social link for {platform} already exists. Please edit it instead.', category='error')
        return redirect(url_for('views.admin_manage_links'))

    icon_class = get_social_icon_class(platform) # Use helper to get icon
    
    new_link = SocialLink(
        platform=platform,
        url=url,
        icon_class=icon_class,
        order=SocialLink.query.count() # Simple ordering
    )
    db.session.add(new_link)
    db.session.commit()
    flash(f'{platform} link added successfully!', category='success')
    return redirect(url_for('views.admin_manage_links'))

@views.route('/admin/delete_social_link/<int:link_id>', methods=['POST'])
@login_required
def admin_delete_social_link(link_id):
    link = SocialLink.query.get_or_404(link_id)
    db.session.delete(link)
    db.session.commit()
    flash(f'{link.platform} link deleted.', category='success')
    return redirect(url_for('views.admin_manage_links'))


@views.route('/admin/add_quick_link', methods=['POST'])
@login_required
def admin_add_quick_link():
    name = request.form.get('name')
    url = request.form.get('url')

    if not name or not url:
        flash('Name and URL are required for quick link.', category='error')
        return redirect(url_for('views.admin_manage_links'))
    
    # Simple check for duplicate name (optional, but good practice)
    existing_link = QuickLink.query.filter_by(name=name).first()
    if existing_link:
        flash(f'A quick link named "{name}" already exists. Please use a different name.', category='error')
        return redirect(url_for('views.admin_manage_links'))

    new_link = QuickLink(
        name=name,
        url=url,
        order=QuickLink.query.count() # Simple ordering
    )
    db.session.add(new_link)
    db.session.commit()
    flash(f'Quick link "{name}" added successfully!', category='success')
    return redirect(url_for('views.admin_manage_links'))

@views.route('/admin/delete_quick_link/<int:link_id>', methods=['POST'])
@login_required
def admin_delete_quick_link(link_id):
    link = QuickLink.query.get_or_404(link_id)
    db.session.delete(link)
    db.session.commit()
    flash(f'Quick link "{link.name}" deleted.', category='success')
    return redirect(url_for('views.admin_manage_links'))

# ==========================================
# ADMIN ROUTES & DASHBOARD
# ==========================================

# HELPER FUNCTION: Get Sidebar Counts
def get_sidebar_counts():
    return {
        'pending_count': Booking.query.filter_by(status='pending', is_archived=False).count(),
        'scheduled_count': Booking.query.filter_by(status='scheduled', is_archived=False).count(),
        'cancelled_count': Booking.query.filter_by(status='cancelled', is_archived=False).count(),
        'archived_count': Booking.query.filter_by(is_archived=True).count() + ContactMessage.query.filter_by(is_archived=True).count()
    }



# Helper function to get monthly booking data for the chart (Based on Event Date)
def get_monthly_booking_data():
    today = datetime.now()
    
    monthly_booked = {}
    monthly_cancelled = {}
    month_labels = []

    # Generate month_keys and labels for the last 12 months
    current_year = today.year
    current_month = today.month
    
    date_tuples = []
    for i in range(12):
        month = (current_month - 1 - i) % 12 + 1
        year = current_year - ((current_month - 1 - i) // 12)
        date_tuples.insert(0, (year, month)) 
        
    for year, month in date_tuples:
        month_key = f"{year:04d}-{month:02d}" # Format YYYY-MM
        month_label = f"{month_abbr[month]} {year}" # E.g., 'Jan 2024'
        monthly_booked[month_key] = 0
        monthly_cancelled[month_key] = 0
        month_labels.append(month_label)

    # Fetch all Booked and Cancelled bookings
    all_relevant_bookings = Booking.query.filter(
        Booking.status.in_(['scheduled', 'cancelled'])
    ).all()

    # Populate counts based on the EVENT DATE (booking.date)
    for booking in all_relevant_bookings:
        if booking.date and len(booking.date) >= 7: # Ensure valid 'YYYY-MM-DD' format
            month_key = booking.date[:7] 
            
            # If the event falls within our 12-month graph window, add it to the count
            if month_key in monthly_booked: 
                if booking.status == 'scheduled':
                    monthly_booked[month_key] += 1
                elif booking.status == 'cancelled':
                    monthly_cancelled[month_key] += 1
    
    # Extract data in the correct order for the Chart.js
    booked_data = [monthly_booked.get(f"{y:04d}-{m:02d}", 0) for y, m in date_tuples]
    cancelled_data = [monthly_cancelled.get(f"{y:04d}-{m:02d}", 0) for y, m in date_tuples]

    return {
        'labels': month_labels,
        'booked_data': booked_data,
        'cancelled_data': cancelled_data
    }

@views.route('/dashboard')
@login_required
def dashboard():
    # Only show active messages on the dashboard
    messages = ContactMessage.query.filter_by(is_archived=False).order_by(ContactMessage.date.desc()).limit(5).all()
    counts = get_sidebar_counts()
    chart_data = get_monthly_booking_data()
    
    return render_template("dashboard.html", user=current_user, messages=messages, 
                           page='dashboard', chart_data=chart_data, **counts)

@views.route('/admin/calendar')
@login_required
def calendar():
    # Only show active scheduled/finished events on the calendar
    bookings = Booking.query.filter(
        Booking.status.in_(['scheduled', 'finished'])
    ).filter_by(is_archived=False).all()
    
    events = []
    
    for booking in bookings:
        start_datetime = f"{booking.date}T{booking.time}:00" if booking.date and booking.time else ""
        
        background_color = '#10B981' # Default Green
        if booking.service_type == 'Photobooth':
            background_color = '#4F46E5' # Indigo for Photobooth
        if booking.status == 'finished':
            background_color = '#15803D' # Darker green for finished
            
        events.append({
            'title': f"{booking.customer_name} - {booking.service_type}",
            'start': start_datetime,
            'backgroundColor': background_color,
            'borderColor': 'transparent',
            'extendedProps': {
                'customer': booking.customer_name,
                'email': booking.customer_email,
                'service': booking.service_type,
                'package': booking.package_selected or 'N/A',
                'location': booking.location or 'In Studio',
                'notes': booking.notes or 'None',
                'status': booking.status
            }
        })

    counts = get_sidebar_counts()
    return render_template("admin_calendar.html", user=current_user, page='dashboard', events=events, **counts)


# --- ACTIVE BOOKING STATUS PAGES ---

@views.route('/admin/pending_bookings')
@login_required
def pending_bookings():
    bookings = Booking.query.filter_by(status='pending', is_archived=False).order_by(Booking.created_at.desc()).all()
    counts = get_sidebar_counts()
    return render_template("admin_pending_bookings.html", user=current_user, page='dashboard', bookings=bookings, **counts)

@views.route('/admin/booked_bookings')
@login_required
def booked_bookings():
    bookings = Booking.query.filter_by(status='scheduled', is_archived=False).order_by(Booking.created_at.desc()).all()
    counts = get_sidebar_counts()
    return render_template("admin_booked_bookings.html", user=current_user, page='dashboard', bookings=bookings, **counts)

@views.route('/admin/cancelled_bookings')
@login_required
def cancelled_bookings():
    bookings = Booking.query.filter_by(status='cancelled', is_archived=False).order_by(Booking.created_at.desc()).all()
    counts = get_sidebar_counts()
    return render_template("admin_cancelled_bookings.html", user=current_user, page='dashboard', bookings=bookings, **counts)

@views.route('/admin/booking_records')
@login_required
def booking_records():
    # 1. Get filter parameters from the URL
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    status_filter = request.args.get('status', 'all')
    service_filter = request.args.get('service', 'all')

    # 2. Build the database query
    query = Booking.query.filter_by(is_archived=False)

    if start_date:
        query = query.filter(Booking.date >= start_date)
    if end_date:
        query = query.filter(Booking.date <= end_date)
    if status_filter and status_filter != 'all':
        query = query.filter(Booking.status == status_filter)
    if service_filter and service_filter != 'all':
        query = query.filter(Booking.service_type == service_filter)

    # 3. Fetch results
    bookings = query.order_by(Booking.created_at.desc()).all()
    
    # 4. Gather filters into a dictionary to send back to the HTML
    active_filters = {
        'start_date': start_date,
        'end_date': end_date,
        'status': status_filter,
        'service': service_filter
    }

    counts = get_sidebar_counts()
    return render_template("admin_booking_records.html", 
                           user=current_user, 
                           page='dashboard', 
                           bookings=bookings, 
                           filters=active_filters, # This tells the HTML what was picked
                           **counts)

@views.route('/admin/inquiries')
@login_required
def inquiries():
    # Show only active messages
    messages = ContactMessage.query.filter_by(is_archived=False).order_by(ContactMessage.date.desc()).all()
    counts = get_sidebar_counts()
    return render_template("admin_inquiries.html", user=current_user, page='dashboard', messages=messages, **counts)


# --- ARCHIVES TAB PAGE ---

@views.route('/admin/archived_bookings')
@login_required
def archived_bookings():
    tab = request.args.get('tab', 'records') # 'records', 'booked', 'cancelled', 'inquiries'
    counts = get_sidebar_counts()
    
    bookings = []
    messages = []
    
    # Filter by the 'is_archived=True' flag, then split by category
    if tab == 'booked':
        bookings = Booking.query.filter_by(is_archived=True, status='scheduled').order_by(Booking.created_at.desc()).all()
    elif tab == 'cancelled':
        bookings = Booking.query.filter_by(is_archived=True, status='cancelled').order_by(Booking.created_at.desc()).all()
    elif tab == 'inquiries':
        messages = ContactMessage.query.filter_by(is_archived=True).order_by(ContactMessage.date.desc()).all()
    else: # Default: all archived booking records
        bookings = Booking.query.filter_by(is_archived=True).order_by(Booking.created_at.desc()).all()
        
    return render_template("admin_archived_bookings.html", user=current_user, page='dashboard', 
                           tab=tab, bookings=bookings, messages=messages, **counts)


# --- ACTIONS & OPERATIONS ---

@views.route('/admin/edit_booking/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def edit_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    
    if request.method == 'POST':
        booking.customer_name = request.form.get('customer_name')
        booking.customer_email = request.form.get('customer_email')
        booking.customer_phone = request.form.get('customer_phone') # <--- NEW PHONE FIELD
        booking.service_type = request.form.get('service_type')
        booking.package_selected = request.form.get('package_selected')
        booking.location = request.form.get('location')
        booking.date = request.form.get('date')
        booking.time = request.form.get('time')
        booking.notes = request.form.get('notes')
        
        db.session.commit()
        flash('Booking updated successfully!', category='success')
        return redirect(url_for('views.booked_bookings'))
        
    counts = get_sidebar_counts()
    return render_template("admin_edit_booking.html", user=current_user, page='dashboard', booking=booking, **counts)

@views.route('/admin/update_booking/<int:booking_id>/<string:status>', methods=['POST'])
@login_required
def update_booking_status(booking_id, status):
    booking = Booking.query.get_or_404(booking_id)
    old_status = booking.status
    
    if status in ['scheduled', 'cancelled', 'pending', 'finished']:
        booking.status = status
        db.session.commit()
        
        # TRIGGER NOTIFICATION: Only when moving TO scheduled
        if status == 'scheduled' and old_status != 'scheduled':
            # We MUST pass the phone number here so the SMS logic works!
            async_send_client_email(
                booking.customer_email, # 1
                booking.customer_phone, # 2 (NEW)
                booking.customer_name,  # 3
                booking.service_type,   # 4
                booking.date,           # 5
                booking.time,           # 6
                booking.location        # 7
            )
            flash(f'Booking confirmed! Alert sent to {booking.customer_name}.', category='success')
        else:
            flash(f'Booking marked as {status.capitalize()}.', category='success')
    
    return redirect(request.referrer or url_for('views.pending_bookings'))

# --- ARCHIVING OPERATIONS ---

@views.route('/admin/archive_selected_bookings', methods=['POST'])
@login_required
def archive_selected_bookings():
    selected_bookings_json = request.form.get('selected_bookings')
    
    if not selected_bookings_json:
        flash('No bookings selected for archiving.', category='error')
        return redirect(request.referrer or url_for('views.dashboard'))

    try:
        selected_booking_ids = json.loads(selected_bookings_json)
    except json.JSONDecodeError:
        flash('Error processing selected bookings data.', category='error')
        return redirect(request.referrer or url_for('views.dashboard'))

    archived_count = 0
    for booking_id in selected_booking_ids:
        try:
            booking = Booking.query.get(int(booking_id))
            if booking:
                booking.is_archived = True # Update boolean flag instead of status
                archived_count += 1
        except ValueError:
            continue
    
    db.session.commit()
    if archived_count > 0:
        flash(f'{archived_count} booking(s) successfully moved to archives!', category='success')
    return redirect(request.referrer or url_for('views.archived_bookings'))


@views.route('/admin/unarchive_selected_bookings', methods=['POST'])
@login_required
def unarchive_selected_bookings():
    selected_json = request.form.get('selected_bookings')
    if not selected_json:
        return redirect(request.referrer)
        
    try:
        selected_ids = json.loads(selected_json)
    except json.JSONDecodeError:
        return redirect(request.referrer)

    count = 0
    for b_id in selected_ids:
        try:
            booking = Booking.query.get(int(b_id))
            if booking:
                booking.is_archived = False
                count += 1
        except ValueError:
            continue
            
    db.session.commit()
    if count > 0:
        flash(f'{count} booking(s) successfully restored!', category='success')
    return redirect(request.referrer or url_for('views.archived_bookings'))


@views.route('/admin/unarchive_selected_messages', methods=['POST'])
@login_required
def unarchive_selected_messages():
    selected_json = request.form.get('selected_messages')
    if not selected_json:
        return redirect(request.referrer)
        
    try:
        selected_ids = json.loads(selected_json)
    except json.JSONDecodeError:
        return redirect(request.referrer)

    count = 0
    for m_id in selected_ids:
        try:
            msg = ContactMessage.query.get(int(m_id))
            if msg:
                msg.is_archived = False
                count += 1
        except ValueError:
            continue
            
    db.session.commit()
    if count > 0:
        flash(f'{count} message(s) successfully restored!', category='success')
    return redirect(request.referrer or url_for('views.archived_bookings', tab='inquiries'))


@views.route('/admin/unarchive_booking/<int:booking_id>', methods=['POST'])
@login_required
def unarchive_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.is_archived = False
    db.session.commit()
    flash('Booking restored from archives!', category='success')
    return redirect(request.referrer or url_for('views.archived_bookings'))

@views.route('/admin/archive_message/<int:message_id>', methods=['POST'])
@login_required
def archive_message(message_id):
    msg = ContactMessage.query.get_or_404(message_id)
    msg.is_archived = True
    db.session.commit()
    flash('Message moved to archives.', category='success')
    return redirect(request.referrer or url_for('views.inquiries'))

@views.route('/admin/unarchive_message/<int:message_id>', methods=['POST'])
@login_required
def unarchive_message(message_id):
    msg = ContactMessage.query.get_or_404(message_id)
    msg.is_archived = False
    db.session.commit()
    flash('Message restored from archives.', category='success')
    return redirect(request.referrer or url_for('views.archived_bookings', tab='inquiries'))

@views.route('/admin/delete_message/<int:message_id>', methods=['POST'])
@login_required
def delete_message(message_id):
    msg = ContactMessage.query.get_or_404(message_id)
    db.session.delete(msg)
    db.session.commit()
    flash('Message permanently deleted.', category='success')
    return redirect(request.referrer or url_for('views.inquiries'))


# --- EXPORT TO CSV WITH FILTERS ---

@views.route('/admin/export_bookings')
@login_required
def export_bookings():
    # Get all filter parameters from the URL
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status_filter = request.args.get('status')
    service_filter = request.args.get('service')

    # Start with base query
    query = Booking.query

    # Apply Date Filters
    if start_date:
        query = query.filter(Booking.date >= start_date)
    if end_date:
        query = query.filter(Booking.date <= end_date)
    
    # Apply Status Filter (only if a specific status is chosen)
    if status_filter and status_filter != 'all':
        query = query.filter(Booking.status == status_filter)
        
    # Apply Service Filter (only if a specific service is chosen)
    if service_filter and service_filter != 'all':
        query = query.filter(Booking.service_type == service_filter)
        
    bookings = query.order_by(Booking.date.desc()).all()

    # Generate CSV in memory
    si = io.StringIO()
    cw = csv.writer(si)
    
    # Write Headers (Added Phone Number to export as well)
    cw.writerow([
        'Created On', 'Event Date', 'Event Time', 'Customer Name', 
        'Customer Email', 'Customer Phone', 'Service Type', 'Package Selected', 
        'Location', 'Status', 'Archived' 
    ])
    
    # Write Data Rows
    for b in bookings:
        created = b.created_at.strftime('%Y-%m-%d %H:%M') if b.created_at else 'N/A'
        cw.writerow([
            created,
            b.date,
            b.time,
            b.customer_name,
            b.customer_email,
            b.customer_phone or 'N/A',
            b.service_type,
            b.package_selected or 'N/A',
            b.location or 'In Studio',
            b.status.upper(),
            'YES' if b.is_archived else 'NO'
        ])

    output = si.getvalue()
    
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=bookings_export_{datetime.now().strftime('%Y%m%d')}.csv"}
    )
# =========================================================
# NEW ADMIN PAGES: MANAGE PORTFOLIO, PACKAGES, SETTINGS, ADD RECORD
# =========================================================

# --- MANAGE PORTFOLIO ---

def save_portfolio_image(file):
    if file and file.filename != '' and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(os.path.join(UPLOAD_FOLDER, filename))
        return filename
    return None

def post_to_facebook(app, message, image_filename=None):
    """Universal function to post to FB Page - Context Aware"""
    # This block allows the thread to talk to the database
    with app.app_context():
        page_id = get_setting('fb_page_id')
        access_token = get_setting('fb_access_token')
        
        if not page_id or not access_token:
            print("⚠️ Facebook credentials missing. Skipping post.")
            return

        try:
            if image_filename:
                # Path to the image
                img_path = os.path.join(current_app.root_path, 'static', 'images', image_filename)
                
                if os.path.exists(img_path):
                    url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
                    with open(img_path, 'rb') as img_file:
                        payload = {'caption': message, 'access_token': access_token}
                        files = {'source': img_file}
                        response = requests.post(url, data=payload, files=files)
                else:
                    print(f"⚠️ Image file not found: {img_path}")
                    return
            else:
                # Text only
                url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
                response = requests.post(url, data={'message': message, 'access_token': access_token})
                
            if response.status_code in [200, 201]:
                print("✅ Facebook Post Successful!")
            else:
                print(f"❌ Facebook API Error: {response.text}")
                
        except Exception as e:
            print(f"❌ Facebook Thread Exception: {e}")

@views.route('/admin/portfolio')
@login_required
def admin_portfolio():
    portfolio_items = PortfolioItem.query.order_by(PortfolioItem.created_at.desc()).all()
    counts = get_sidebar_counts()
    return render_template("admin_portfolio.html", user=current_user, page='dashboard', 
                           portfolio_items=portfolio_items, **counts)

@views.route('/admin/portfolio/add', methods=['GET', 'POST'])
@login_required
def admin_add_portfolio():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        link = request.form.get('link')
        
        # Helper to save files
        def save_file(file):
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                return filename
            return None

        # 1. Save standard slots 1, 2, and 3
        img1 = save_file(request.files.get('image_file'))
        img2 = save_file(request.files.get('image_file_2'))
        img3 = save_file(request.files.get('image_file_3'))
        
        # 2. Handle 4th slot + extra media list
        extra_files = request.files.getlist('extra_media')
        extra_media_list = []
        img4 = None
        extra_count = ""

        if extra_files and extra_files[0].filename != '':
            for i, file in enumerate(extra_files):
                filename = save_file(file)
                if filename:
                    extra_media_list.append(filename)
                    if i == 0:
                        img4 = filename 
            
            if len(extra_media_list) > 1:
                extra_count = str(len(extra_media_list) - 1)

        if not title or not img1:
            flash('Title and the Main Media (Slot 1) are required.', category='error')
        else:
            # 3. Save to Database
            new_item = PortfolioItem(
                title=title,
                description=description,
                category=category,
                link=link,
                image_filename=img1,
                image_filename_2=img2,
                image_filename_3=img3,
                image_filename_4=img4,
                extra_count=extra_count,
                extra_media=json.dumps(extra_media_list) if extra_media_list else None
            )
            db.session.add(new_item)
            db.session.commit()

            # 4. TRIGGER MULTI-MEDIA FACEBOOK POST
            app = current_app._get_current_object()
            threading.Thread(target=post_portfolio_to_facebook, args=(app, new_item.id)).start()

            flash('Portfolio item added and sharing to Facebook Page!', category='success')
            return redirect(url_for('views.admin_portfolio'))
            
    return render_template("admin_add_edit_portfolio.html", user=current_user, item=None, **get_sidebar_counts())

@views.route('/admin/portfolio/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_portfolio(item_id):
    item = PortfolioItem.query.get_or_404(item_id)

    if request.method == 'POST':
        item.title = request.form.get('title')
        item.description = request.form.get('description')
        item.category = request.form.get('category')
        item.link = request.form.get('link')
        
        # Simple update: Check for file replacements
        def save_file(file):
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                return filename
            return None

        f1 = save_file(request.files.get('image_file'))
        if f1: item.image_filename = f1
        # ... (Repeat for slots 2, 3, 4 if you want to allow individual replacement)

        db.session.commit()

        # Update Facebook Caption if post exists
        if item.fb_post_id:
            token = get_setting('fb_access_token')
            if token:
                new_caption = f"✨ {item.title}\n📂 Category: {item.category}\n\n{item.description}"
                requests.post(f"https://graph.facebook.com/v19.0/{item.fb_post_id}", 
                              data={'message': new_caption, 'access_token': token})

        flash('Portfolio item updated successfully!', category='success')
        return redirect(url_for('views.admin_portfolio'))

    return render_template("admin_add_edit_portfolio.html", user=current_user, item=item, **get_sidebar_counts())

@views.route('/admin/portfolio/delete/<int:item_id>', methods=['POST'])
@login_required
def admin_delete_portfolio(item_id):
    item = PortfolioItem.query.get_or_404(item_id)
    
    # 1. Delete from Facebook first (if a post ID exists)
    if item.fb_post_id:
        # --- THE FIX: GET APP AND PASS IT ---
        app = current_app._get_current_object()
        threading.Thread(target=delete_facebook_post, args=(app, item.fb_post_id)).start()
        
    # 2. Delete from local Database
    db.session.delete(item)
    db.session.commit()
    
    flash('Item deleted from website and Facebook queue.', category='success')
    return redirect(url_for('views.admin_portfolio'))

# --- PACKAGES & PRICING ---
@views.route('/admin/packages_pricing')
@login_required
def admin_packages_pricing():
    packages = ServicePackage.query.order_by(ServicePackage.name).all()
    counts = get_sidebar_counts()
    return render_template("admin_packages_pricing.html", user=current_user, page='dashboard', 
                           packages=packages, **counts)

@views.route('/admin/packages_pricing/add', methods=['GET', 'POST'])
@login_required
def admin_add_package():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = request.form.get('price')
        package_type = request.form.get('package_type')
        
        # Handle Package Image
        file = request.files.get('image_file')
        img = None
        if file and file.filename != '' and allowed_file(file.filename):
            img = secure_filename(file.filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file.save(os.path.join(UPLOAD_FOLDER, img))

        if not name or not price:
            flash('Name and Price are required.', category='error')
        else:
            # 1. Save to Database
            new_package = ServicePackage(
                name=name,
                description=description,
                price=price,
                package_type=package_type,
                image_filename=img
            )
            db.session.add(new_package)
            db.session.commit()

            # 2. TRIGGER AUTOMATIC FACEBOOK POST (Context Aware)
            fb_msg = f"📸 NEW SERVICE PACKAGE: {name}\n💰 Price: {price}\n\n{description}\n\nBook your session today!"
            
            # Get the real app object to pass into the background thread
            app = current_app._get_current_object()
            threading.Thread(target=post_to_facebook, args=(app, fb_msg, img)).start()

            flash('Package added and shared to Facebook!', category='success')
            return redirect(url_for('views.admin_packages_pricing'))

    return render_template("admin_add_edit_package.html", user=current_user, package=None, **get_sidebar_counts())

@views.route('/admin/packages_pricing/edit/<int:package_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_package(package_id):
    package = ServicePackage.query.get_or_404(package_id)

    if request.method == 'POST':
        package.name = request.form.get('name')
        package.description = request.form.get('description')
        package.price = request.form.get('price')
        package.package_type = request.form.get('package_type')
        
        # Handle Package Image Replacement
        file = request.files.get('image_file')
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file.save(os.path.join(UPLOAD_FOLDER, filename))
            package.image_filename = filename
        
        db.session.commit()
        flash('Package updated successfully!', category='success')
        return redirect(url_for('views.admin_packages_pricing'))

    counts = get_sidebar_counts()
    return render_template("admin_add_edit_package.html", user=current_user, page='dashboard', package=package, **counts)

@views.route('/admin/packages_pricing/delete/<int:package_id>', methods=['POST'])
@login_required
def admin_delete_package(package_id):
    package = ServicePackage.query.get_or_404(package_id)
    db.session.delete(package)
    db.session.commit()
    flash('Package deleted successfully!', category='success')
    return redirect(url_for('views.admin_packages_pricing'))


# --- SYSTEM SETTINGS (Placeholder) ---
@views.route('/admin/settings')
@login_required
def admin_settings():
    counts = get_sidebar_counts()
    return render_template("admin_settings.html", user=current_user, page='dashboard', **counts)


# --- ADD NEW RECORD (Booking) ---
@views.route('/admin/add_record', methods=['GET', 'POST'])
@login_required
def admin_add_record():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name')
        customer_email = request.form.get('customer_email')
        customer_phone = request.form.get('customer_phone') # <--- NEW PHONE FIELD
        service_type = request.form.get('service_type')
        package_selected = request.form.get('package_selected')
        location = request.form.get('location')
        map_url = request.form.get('map_url')
        date = request.form.get('date')
        time = request.form.get('time')
        notes = request.form.get('notes')
        status = request.form.get('status', 'scheduled') # Admin can set initial status

        if not customer_name or not customer_email or not customer_phone or not service_type or not date or not time:
            flash('Customer Name, Email, Phone, Service Type, Date, and Time are required.', category='error')
        else:
            new_booking = Booking(
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone, # <--- SAVING PHONE TO DB
                service_type=service_type,
                package_selected=package_selected,
                location=location,
                map_url=map_url,
                date=date,
                time=time,
                notes=notes,
                status=status,
                is_archived=False
            )
            db.session.add(new_booking)
            db.session.commit()
            flash(f'New booking for {customer_name} added successfully!', category='success')
            return redirect(url_for('views.booked_bookings')) # Redirect to booked page

    counts = get_sidebar_counts()
    return render_template("admin_add_record.html", user=current_user, page='dashboard', **counts)

@views.route('/admin/cms')
@login_required
def admin_cms():
    counts = get_sidebar_counts()
    return render_template("admin_cms.html", user=current_user, page='dashboard', **counts)

# ==========================================
# SUPER ADMIN: USER MANAGEMENT ROUTES
# ==========================================



@views.route('/admin/super_admin/save_notification_settings', methods=['POST'])
@login_required
def save_notification_settings():
    if current_user.role != 'super_admin':
        return redirect(url_for('views.dashboard'))
    
    new_email = request.form.get('notification_email')
    new_hours = request.form.get('reminder_hours')
    new_admin_phone = request.form.get('admin_phone') # ADD THIS
    if new_admin_phone:
        set_setting('admin_phone_number', new_admin_phone)

    if new_email:
        set_setting('notification_recipient_email', new_email)
    
    if new_hours:
        set_setting('reminder_hours_before', new_hours)
        
    db.session.commit()
    flash('Notification settings updated successfully!', 'success')
    return redirect(url_for('views.super_admin_dashboard'))

@views.route('/admin/super_admin')
@login_required
def super_admin_dashboard():
    if current_user.role != 'super_admin': 
        return redirect(url_for('views.dashboard'))
        
    users = User.query.all()
    counts = get_sidebar_counts()
    
    return render_template("admin_super_admin.html", 
                           user=current_user, 
                           users=users, 
                           page='dashboard', 
                           maintenance_mode=get_setting('site_maintenance_mode', 'false'), 
                           notification_email=get_setting('notification_recipient_email', 'enemyslayer0909@gmail.com'),
                           reminder_hours=get_setting('reminder_hours_before', '24'),
                           **counts)

@views.route('/admin/super_admin/toggle_maintenance', methods=['POST'])
@login_required
def toggle_maintenance():
    if current_user.role != 'super_admin':
        return redirect(url_for('views.dashboard'))
    
    current_status = get_setting('site_maintenance_mode', 'false')
    new_status = 'false' if current_status == 'true' else 'true'
    
    set_setting('site_maintenance_mode', new_status)
    db.session.commit()
    
    if new_status == 'true':
        flash('⚠️ Website is now UNDER MAINTENANCE. Public access is disabled.', 'error')
    else:
        flash('✅ Website is now LIVE to the public.', 'success')
        
    return redirect(url_for('views.super_admin_dashboard'))

@views.route('/admin/super_admin/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def super_admin_edit_user(user_id):
    if current_user.role != 'super_admin':
        flash('Access denied.', category='error')
        return redirect(url_for('views.dashboard'))
    
    target_user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        target_user.username = request.form.get('username')
        target_user.first_name = request.form.get('first_name')
        target_user.role = request.form.get('role')
        
        new_password = request.form.get('password')
        if new_password and new_password.strip() != "":
            target_user.password = generate_password_hash(new_password, method='scrypt')
        
        db.session.commit()
        flash('User details updated successfully!', category='success')
        return redirect(url_for('views.super_admin_dashboard'))
        
    counts = get_sidebar_counts()
    return render_template("admin_edit_user.html", user=current_user, target_user=target_user, users=User.query.all(), page='dashboard', **counts)

@views.route('/admin/super_admin/delete/<int:user_id>', methods=['POST'])
@login_required
def super_admin_delete_user(user_id):
    if current_user.role != 'super_admin':
        return redirect(url_for('views.dashboard'))
        
    if current_user.id == user_id:
        flash('You cannot delete your own account.', category='error')
        return redirect(url_for('views.super_admin_dashboard'))
    
    target_user = User.query.get_or_404(user_id)
    db.session.delete(target_user)
    db.session.commit()
    flash('User deleted successfully.', category='success')
    return redirect(url_for('views.super_admin_dashboard'))

@views.before_request
def check_maintenance_mode():
    # Allow access to all admin routes and static files
    if request.path.startswith('/admin') or request.path.startswith('/static'):
        return
        
    # Allow access to the maintenance page itself
    if request.path == '/maintenance':
        return
        
    # Check if maintenance mode is ON
    maintenance = get_setting('site_maintenance_mode', 'false')
    if maintenance == 'true':
        # Let logged-in admins bypass maintenance mode so they can preview the live site
        if current_user.is_authenticated:
            return
        # Redirect all regular public traffic to the maintenance page
        return redirect(url_for('views.maintenance'))

# --- MAINTENANCE PAGE ROUTE ---
@views.route('/maintenance')
def maintenance():
    # If maintenance mode is OFF, send them back to the home page
    if get_setting('site_maintenance_mode', 'false') != 'true':
        return redirect(url_for('views.home'))

    return render_template('maintenance.html', user=current_user, page='maintenance')

# ==========================================
# SYSTEM: BACKUP & RESTORE 
# ==========================================

def get_actual_db_path():
    """Helper to find the database file in various possible locations"""
    # 1. Try absolute path in root folder
    # 2. Try 'website' folder
    # 3. Try 'instance' folder
    base_dir = os.path.abspath(os.path.dirname(__file__)) # website/ folder
    root_dir = os.path.abspath(os.path.join(base_dir, '..')) # project root
    
    possible_paths = [
        os.path.join(base_dir, 'database.db'),
        os.path.join(root_dir, 'database.db'),
        os.path.join(root_dir, 'instance', 'database.db')
    ]
    
    for p in possible_paths:
        if os.path.exists(p):
            return p
    return None

@views.route('/admin/system/backup')
@login_required
def admin_backup_db():
    if current_user.role != 'super_admin':
        flash('Access denied.', 'error')
        return redirect(url_for('views.dashboard'))

    db_path = get_actual_db_path()
    
    if db_path:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        return send_file(db_path, as_attachment=True, download_name=f"wandershots_backup_{timestamp}.db")
    else:
        # Debugging info: print the directory to console
        print(f"DEBUG: Current directory is {os.getcwd()}")
        flash('Database file not found on the server. Please check file structure.', 'error')
        return redirect(url_for('views.admin_settings'))


@views.route('/admin/system/restore', methods=['POST'])
@login_required
def admin_restore_db():
    if current_user.role != 'super_admin':
        return redirect(url_for('views.dashboard'))

    file = request.files.get('backup_file')
    db_path = get_actual_db_path()
    
    if not db_path:
        flash('Cannot restore: Original database path not found.', 'error')
        return redirect(url_for('views.admin_settings'))

    if file and file.filename.endswith('.db'):
        # 1. Create safety backup
        shutil.copy(db_path, db_path + ".bak")
        
        try:
            # 2. Overwrite current DB
            file.save(db_path)
            flash('Database restored successfully! Logging out to refresh session.', 'success')
            return redirect(url_for('auth.logout')) 
        except Exception as e:
            shutil.copy(db_path + ".bak", db_path)
            flash(f'Restoration failed: {e}', 'error')
    else:
        flash('Invalid file format. Please upload a .db file.', 'error')
        
    return redirect(url_for('views.admin_settings'))

@views.route('/admin/super_admin/save_fb_settings', methods=['POST'])
@login_required
def save_fb_settings():
    if current_user.role != 'super_admin': return redirect(url_for('views.dashboard'))
    set_setting('fb_page_id', request.form.get('fb_page_id'))
    set_setting('fb_access_token', request.form.get('fb_access_token'))
    db.session.commit()
    flash('Facebook settings updated!', 'success')
    return redirect(url_for('views.super_admin_dashboard'))

def post_package_to_facebook(name, price, description, image_filename=None):
    page_id = get_setting('fb_page_id')
    access_token = get_setting('fb_access_token')
    
    if not page_id or not access_token:
        print("Facebook credentials missing. Skipping post.")
        return

    message = f"📸 NEW SERVICE PACKAGE: {name}\n\nPrice: {price}\n\nDetails: {description}\n\nBook your session now with Wandershots Studios!"
    
    try:
        if image_filename:
            # Posting with an Image
            img_path = os.path.join(current_app.root_path, 'static/images', image_filename)
            url = f"https://graph.facebook.com/{page_id}/photos"
            with open(img_path, 'rb') as img_file:
                payload = {'caption': message, 'access_token': access_token}
                files = {'source': img_file}
                response = requests.post(url, data=payload, files=files)
        else:
            # Text only post
            url = f"https://graph.facebook.com/{page_id}/feed"
            payload = {'message': message, 'access_token': access_token}
            response = requests.post(url, data=payload)
            
        if response.status_code == 200:
            print("✅ Successfully posted to Facebook Page!")
        else:
            print(f"❌ Facebook API Error: {response.text}")
    except Exception as e:
        print(f"❌ Facebook Exception: {e}")

# ==========================================
# ADMIN: INVENTORY MANAGEMENT
# ==========================================

@views.route('/admin/inventory')
@login_required
def admin_inventory():
    items = InventoryItem.query.order_by(InventoryItem.category).all()
    counts = get_sidebar_counts()
    return render_template("admin_inventory.html", user=current_user, items=items, page='dashboard', **counts)

@views.route('/admin/inventory/add', methods=['GET', 'POST'])
@login_required
def admin_add_inventory():
    if request.method == 'POST':
        new_item = InventoryItem(
            name=request.form.get('name'),
            category=request.form.get('category'),
            quantity=int(request.form.get('quantity') or 0),
            min_stock=int(request.form.get('min_stock') or 5),
            unit=request.form.get('unit')
        )
        db.session.add(new_item)
        db.session.commit()
        flash(f'Item {new_item.name} added to inventory.', 'success')
        return redirect(url_for('views.admin_inventory'))
    
    return render_template("admin_add_edit_inventory.html", user=current_user, item=None, **get_sidebar_counts())

@views.route('/admin/inventory/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_inventory(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    if request.method == 'POST':
        item.name = request.form.get('name')
        item.category = request.form.get('category')
        item.quantity = int(request.form.get('quantity'))
        item.min_stock = int(request.form.get('min_stock'))
        item.unit = request.form.get('unit')
        db.session.commit()
        flash('Inventory updated.', 'success')
        return redirect(url_for('views.admin_inventory'))
    
    return render_template("admin_add_edit_inventory.html", user=current_user, item=item, **get_sidebar_counts())

@views.route('/admin/inventory/quick-update/<int:item_id>/<string:action>', methods=['POST'])
@login_required
def admin_inventory_quick_update(item_id, action):
    item = InventoryItem.query.get_or_404(item_id)
    if action == 'add':
        item.quantity += 1
    elif action == 'sub' and item.quantity > 0:
        item.quantity -= 1
    db.session.commit()
    return redirect(url_for('views.admin_inventory'))

@views.route('/admin/inventory/delete/<int:item_id>', methods=['POST'])
@login_required
def admin_delete_inventory(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('Item removed from inventory.', 'success')
    return redirect(url_for('views.admin_inventory'))