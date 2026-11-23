"""Lightweight security helpers used by the Google Calendar integration."""

from __future__ import annotations

import secrets
from functools import wraps

from flask import abort, request, session
from flask_login import current_user

ADMIN_ROLES = ('admin', 'super_admin')
CSRF_SESSION_KEY = '_wandershots_csrf_token'


def get_csrf_token():
    """Return the per-session CSRF token, creating it when necessary."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf():
    """Validate a CSRF token from a form field or the X-CSRF-Token header."""
    expected = session.get(CSRF_SESSION_KEY)
    supplied = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not expected or not supplied:
        return False
    return secrets.compare_digest(str(expected), str(supplied))


def require_csrf():
    """Abort with 400 when the request does not carry a valid CSRF token."""
    if not validate_csrf():
        abort(400, description='Invalid or missing CSRF token.')


def admin_required(view):
    """Restrict an endpoint to authenticated admin/super-admin accounts."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, 'role', None) not in ADMIN_ROLES:
            abort(403)
        return view(*args, **kwargs)
    return wrapped
