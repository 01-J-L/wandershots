import os # NEW: Import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, current_app
from .models import User
from werkzeug.security import check_password_hash, generate_password_hash
from . import db, oauth # IMPORT OAUTH FROM INIT
from flask_login import login_user, login_required, logout_user, current_user
import random
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import email.utils
import threading

auth = Blueprint('auth', __name__)

# --- HELPER: SPAM-PROOF EMAIL CONFIGURATION ---
def create_secure_message(subject, recipient_email, html_body, plain_body):
    SMTP_USER = os.environ.get("SMTP_USER") # NEW: Get from env var
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = email.utils.formataddr(('Wandershots Studios', SMTP_USER))
    msg['To'] = recipient_email
    msg['Message-ID'] = email.utils.make_msgid()
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg.add_header('Auto-Submitted', 'auto-generated')
    msg.add_header('X-Priority', '3')
    
    part1 = MIMEText(plain_body, 'plain', 'utf-8')
    part2 = MIMEText(html_body, 'html', 'utf-8')
    msg.attach(part1)
    msg.attach(part2)
    return msg, SMTP_USER

def send_email_thread(msg, smtp_user, smtp_pass):
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

# --- HELPER: SEND PASSWORD RESET OTP ---
def send_otp_async(app, recipient_email, otp_code, first_name):
    with app.app_context():
        SMTP_PASS = os.environ.get("SMTP_PASS") # NEW: Get from env var
        plain_body = f"Hi {first_name},\nYour verification code is: {otp_code}\nExpires in 10 minutes.\nThanks,\nThe Wandershots Studios Team"
        html_body = f"<html><body style='font-family: Arial, sans-serif; padding: 20px;'><h2 style='color: #4f46e5;'>Wandershots Studios</h2><p>Hi <b>{first_name}</b>,</p><p>Your verification code:</p><div style='font-size: 36px; font-weight: bold; color: #111827;'>{otp_code}</div><p style='font-size: 13px; color: #5f6368;'>Expires in 10 minutes.</p></body></html>"
        msg, smtp_user = create_secure_message("Your Wandershots verification code", recipient_email, html_body, plain_body)
        send_email_thread(msg, smtp_user, SMTP_PASS)

# --- HELPER: SEND SIGN-UP OTP ---
def send_signup_otp_async(app, recipient_email, otp_code, first_name):
    with app.app_context():
        SMTP_PASS = os.environ.get("SMTP_PASS") # NEW: Get from env var
        plain_body = f"Hi {first_name},\nYour verification code is: {otp_code}\nExpires in 10 minutes.\nThanks,\nThe Wandershots Studios Team"
        html_body = f"<html><body style='font-family: Arial, sans-serif; padding: 20px;'><h2 style='color: #4f46e5;'>Wandershots Studios</h2><p>Hi <b>{first_name}</b>,</p><p>Verify your email to complete registration:</p><div style='font-size: 36px; font-weight: bold; color: #111827;'>{otp_code}</div><p style='font-size: 13px; color: #5f6368;'>Expires in 10 minutes.</p></body></html>"
        msg, smtp_user = create_secure_message("Your Wandershots verification code", recipient_email, html_body, plain_body)
        send_email_thread(msg, smtp_user, SMTP_PASS)

# ===============================================
# SOCIAL LOGIN ROUTES (GOOGLE & FACEBOOK)
# ===============================================

@auth.route('/login/google')
def login_google():
    if request.args.get('next'):
        session['next_url'] = request.args.get('next')
    redirect_uri = url_for('auth.authorize_google', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri)

@auth.route('/authorize/google')
def authorize_google():
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            user_info = oauth.google.userinfo()
            
        email = user_info.get('email')
        name = user_info.get('name')
        
        if not email:
            flash('Email not provided by Google.', 'error')
            return redirect(url_for('auth.login'))
            
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, first_name=name, role='customer', password='')
            db.session.add(user)
            db.session.commit()
            
        login_user(user, remember=True)
        flash(f'Welcome, {user.first_name}!', 'success')
        next_url = session.pop('next_url', None)
        return redirect(next_url or url_for('views.customer_dashboard'))
    except Exception as e:
        flash('Google login failed or was cancelled.', 'error')
        return redirect(url_for('auth.login'))

@auth.route('/login/facebook')
def login_facebook():
    if request.args.get('next'):
        session['next_url'] = request.args.get('next')
    redirect_uri = url_for('auth.authorize_facebook', _external=True, _scheme='https')
    return oauth.facebook.authorize_redirect(redirect_uri)

@auth.route('/authorize/facebook')
def authorize_facebook():
    try:
        token = oauth.facebook.authorize_access_token()
        resp = oauth.facebook.get('me?fields=id,name,email')
        user_info = resp.json()
        
        email = user_info.get('email')
        name = user_info.get('name')
        
        if not email:
            flash('Email not provided by Facebook. Ensure your account has an email address.', 'error')
            return redirect(url_for('auth.login'))
            
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, first_name=name, role='customer', password='')
            db.session.add(user)
            db.session.commit()
            
        login_user(user, remember=True)
        flash(f'Welcome, {user.first_name}!', 'success')
        next_url = session.pop('next_url', None)
        return redirect(next_url or url_for('views.customer_dashboard'))
        
    except Exception as e:
        print(f"❌ FACEBOOK OAUTH ERROR: {str(e)}") 
        
        flash('Facebook login failed or was cancelled.', 'error')
        return redirect(url_for('auth.login'))

# ===============================================

# --- CUSTOMER LOGIN ---
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('views.home'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(email=email, role='customer').first()
        if user:
            if user.password and check_password_hash(user.password, password):
                flash(f'Welcome back, {user.first_name}!', category='success')
                login_user(user, remember=remember)
                return redirect(request.args.get('next') or url_for('views.customer_dashboard'))
            elif not user.password:
                flash('This account was created via social login. Please sign in with Google or Facebook.', category='error')
            else:
                flash('Incorrect password.', category='error')
        else:
            flash('Incorrect email or password.', category='error')

    return render_template("customer_login.html", user=current_user, page='auth')

# --- CUSTOMER SIGNUP (STEP 1) ---
@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('views.home'))
        
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please log in.', category='error')
        elif password != confirm_password:
            flash('Passwords do not match.', category='error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', category='error')
        else:
            otp = str(random.randint(100000, 999999))
            expiry_time = datetime.now() + timedelta(minutes=10)
            
            session['signup_data'] = {
                'first_name': first_name, 'email': email, 'phone': phone,
                'password_hash': generate_password_hash(password, method='scrypt')
            }
            session['signup_otp'] = otp
            session['signup_otp_expiry'] = expiry_time.timestamp()
            session['signup_next'] = request.args.get('next')
            
            app = current_app._get_current_object()
            threading.Thread(target=send_signup_otp_async, args=(app, email, otp, first_name)).start()
            
            flash('An OTP has been sent to your email to verify your account.', category='success')
            return redirect(url_for('auth.verify_signup_otp'))

    return render_template("customer_signup.html", user=current_user, page='auth')

# --- VERIFY SIGNUP OTP (STEP 2) ---
@auth.route('/verify-signup-otp', methods=['GET', 'POST'])
def verify_signup_otp():
    if 'signup_data' not in session:
        flash('Session expired. Please sign up again.', 'error')
        return redirect(url_for('auth.signup'))
        
    email = session['signup_data'].get('email')
    expiry_timestamp = session.get('signup_otp_expiry', 0)

    if request.method == 'POST':
        entered_otp = request.form.get('otp')
        stored_otp = session.get('signup_otp')
        
        if datetime.now().timestamp() > expiry_timestamp:
            flash('OTP has expired. Please click Resend OTP.', 'error')
        elif entered_otp == stored_otp:
            if not User.query.filter_by(email=email).first():
                new_user = User(
                    email=email, first_name=session['signup_data'].get('first_name'),
                    phone=session['signup_data'].get('phone'), role='customer',
                    password=session['signup_data'].get('password_hash')
                )
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user, remember=True)
                flash('Account verified and created successfully!', 'success')
                
                next_page = session.get('signup_next')
                session.pop('signup_data', None); session.pop('signup_otp', None)
                session.pop('signup_otp_expiry', None); session.pop('signup_next', None)
                return redirect(next_page or url_for('views.book'))
        else:
            flash('Invalid OTP. Please try again.', 'error')

    return render_template('verify_signup_otp.html', user=current_user, page='auth', email=email, expiry_timestamp=expiry_timestamp)

# --- RESEND SIGNUP OTP ---
@auth.route('/resend-signup-otp')
def resend_signup_otp():
    if 'signup_data' not in session:
        return redirect(url_for('auth.signup'))
        
    otp = str(random.randint(100000, 999999))
    session['signup_otp'] = otp
    session['signup_otp_expiry'] = (datetime.now() + timedelta(minutes=10)).timestamp()
    
    app = current_app._get_current_object()
    threading.Thread(target=send_signup_otp_async, args=(app, session['signup_data']['email'], otp, session['signup_data']['first_name'])).start()
    
    flash('A new OTP has been sent to your email.', 'success')
    return redirect(url_for('auth.verify_signup_otp'))

# --- FORGOT PASSWORD (STEP 1) ---
@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated: return redirect(url_for('views.home'))

    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email, role='customer').first()
        
        if user:
            if not user.password:
                flash("This account uses social login (Google/Facebook). You cannot reset a password here.", "error")
                return redirect(url_for('auth.login'))
                
            otp = str(random.randint(100000, 999999))
            user.otp_code = otp
            user.otp_expiry = datetime.now() + timedelta(minutes=10)
            db.session.commit()
            
            app = current_app._get_current_object()
            threading.Thread(target=send_otp_async, args=(app, email, otp, user.first_name)).start()
            
            session['reset_email'] = email
            flash('An OTP has been sent to your email address.', 'success')
            return redirect(url_for('auth.verify_otp'))
        else:
            flash('No account found with that email address.', 'error')
            
    return render_template('forgot_password.html', user=current_user, page='auth')

# --- VERIFY RESET OTP (STEP 2) ---
@auth.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('reset_email')
    if not email: return redirect(url_for('auth.forgot_password'))
        
    user = User.query.filter_by(email=email).first()
    if not user: return redirect(url_for('auth.forgot_password'))
    
    expiry_timestamp = user.otp_expiry.timestamp() if user.otp_expiry else 0

    if request.method == 'POST':
        entered_otp = request.form.get('otp')
        if user.otp_code == entered_otp:
            if datetime.now() > user.otp_expiry.replace(tzinfo=None):
                flash('OTP has expired. Please click Resend OTP.', 'error')
            else:
                session['otp_verified'] = True
                flash('OTP verified successfully. Create a new password.', 'success')
                return redirect(url_for('auth.reset_password'))
        else:
            flash('Invalid OTP. Please try again.', 'error')
            
    return render_template('verify_otp.html', user=current_user, page='auth', email=email, expiry_timestamp=expiry_timestamp)

# --- RESEND RESET OTP ---
@auth.route('/resend-forgot-otp')
def resend_forgot_otp():
    email = session.get('reset_email')
    user = User.query.filter_by(email=email).first()
    
    if user:
        otp = str(random.randint(100000, 999999))
        user.otp_code = otp
        user.otp_expiry = datetime.now() + timedelta(minutes=10)
        db.session.commit()
        
        app = current_app._get_current_object()
        threading.Thread(target=send_otp_async, args=(app, email, otp, user.first_name)).start()
        flash('A new OTP has been sent to your email.', 'success')
        
    return redirect(url_for('auth.verify_otp'))

# --- RESET PASSWORD (STEP 3) ---
@auth.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified') or not session.get('reset_email'):
        return redirect(url_for('auth.forgot_password'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
        else:
            user = User.query.filter_by(email=session.get('reset_email')).first()
            user.password = generate_password_hash(password, method='scrypt')
            user.otp_code = None
            user.otp_expiry = None
            db.session.commit()
            
            session.pop('reset_email', None); session.pop('otp_verified', None)
            flash('Password reset successfully! You can now log in.', 'success')
            return redirect(url_for('auth.login'))
            
    return render_template('reset_password.html', user=current_user, page='auth')

# --- ADMIN LOGIN & LOGOUT ---
@auth.route('/admin_login', methods=['GET', 'POST'])
@auth.route('/superadmin@login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user, remember=True)
            return redirect(url_for('views.dashboard'))
        flash('Account not found or incorrect password.', 'error')
    return render_template("admin_login.html", user=current_user, page='auth')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('views.home'))