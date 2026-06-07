from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from .models import User
from . import db
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

auth = Blueprint("auth", __name__)
limiter = Limiter(key_func=get_remote_address)
# ==========================================
#           SUB-ADMIN LOGIN (/login)
# ==========================================
@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    # If already logged in
    if current_user.is_authenticated:
        if current_user.is_super_admin:
            return redirect(url_for("views.dashboard")) # Or redirect to super admin login if strict
        return redirect(url_for("views.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pw    = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        
        # Check credentials
        if user and check_password_hash(user.password, pw):
            
            # 1. Check if user is a Super Admin trying to login here
            if user.is_super_admin:
                flash("Super Admins must use the Secure Admin Portal.", "error")
                return redirect(url_for("auth.super_admin_login"))
            
            # 2. Check if user is a Sub-Admin
            if user.is_admin:
                login_user(user, remember=True)
                return redirect(url_for("views.dashboard"))
            else:
                # Normal user (if any exist)
                login_user(user, remember=True)
                return redirect(url_for("views.home"))
        else:
            flash("Invalid credentials.", "error")

    return render_template("login.html")

# ==========================================
#       SUPER ADMIN LOGIN (/admin@login)
# ==========================================
@auth.route("/admin@login", methods=["GET", "POST"])
@limiter.limit("2 per minute")
def super_admin_login():
    # If already logged in
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pw    = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        # Check credentials
        if user and check_password_hash(user.password, pw):
            
            # STRICT CHECK: Must be Super Admin
            if user.is_super_admin:
                login_user(user, remember=True)
                flash("Welcome back, Super Administrator.", "success")
                return redirect(url_for("views.dashboard"))
            else:
                flash("Unauthorized. This portal is for Super Admins only.", "error")
                return redirect(url_for("auth.login"))
        else:
            flash("Invalid Super Admin credentials.", "error")

    return render_template("admin_login.html")

@auth.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("views.home"))