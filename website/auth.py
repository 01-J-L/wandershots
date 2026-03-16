# --- START OF FILE auth.py ---
from flask import Blueprint, render_template, request, flash, redirect, url_for
from .models import User
from werkzeug.security import check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user

auth = Blueprint('auth', __name__)

# Both routes lead to the same login logic
@auth.route('/admin_login', methods=['GET', 'POST'])
@auth.route('/superadmin@login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username') # Changed to username
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user:
            if check_password_hash(user.password, password):
                flash(f'Welcome back, {user.first_name}!', category='success')
                login_user(user, remember=True)
                return redirect(url_for('views.dashboard'))
            else:
                flash('Incorrect password.', category='error')
        else:
            flash('Account not found.', category='error')

    return render_template("admin_login.html", user=current_user, page='auth')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.admin_login'))