"""Google Calendar OAuth 2.0 and booking synchronization service.

Design notes
------------
* OAuth tokens are encrypted at rest with Fernet. The encryption key is derived
  from ``GOOGLE_TOKEN_ENCRYPTION_KEY`` when supplied, otherwise from the Flask
  secret key.
* Google API calls are never made on the request that confirms a booking. A
  durable queue row (``BookingCalendarSync``) is written first and processed by
  a short-lived worker thread and/or the recurring APScheduler poller.
* Event creation is idempotent: the Google event ID is deterministic for a
  booking/connection/generation tuple, and the unique ``(booking_id,
  connection_id)`` constraint prevents duplicate mappings.
* All timestamps sent to Google use ``Asia/Manila`` regardless of server
  timezone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, session, url_for
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError

from . import db
from .models import Booking, BookingCalendarSync, GoogleCalendarConnection

logger = logging.getLogger(__name__)

CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar.events'
CALENDAR_SCOPES = [CALENDAR_SCOPE, 'openid', 'email']
BOOKING_TIMEZONE_NAME = 'Asia/Manila'
BOOKING_TIMEZONE = ZoneInfo(BOOKING_TIMEZONE_NAME)
OAUTH_STATE_SESSION_KEY = 'google_calendar_oauth_state'
OAUTH_STARTED_SESSION_KEY = 'google_calendar_oauth_started_at'
OAUTH_VERIFIER_SESSION_KEY = 'google_calendar_code_verifier'
MAX_RETRIES = 8
STALE_PROCESSING_MINUTES = 15

SERVICE_DURATION_MINUTES = {
    'Events Photography': 480,
    'On-site Studio Booth': 240,
    'Photobooth': 180,
    'Photoman': 240,
    'Studio Photoshoot': 120,
}


class CalendarIntegrationError(Exception):
    """Base exception for calendar integration failures."""


class ReconnectRequired(CalendarIntegrationError):
    """Raised when the stored Google credentials can no longer be used."""


def utcnow():
    """Return a naive UTC datetime for MySQL DATETIME columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_utc(value):
    if not value:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat()


def _fernet():
    explicit = os.environ.get('GOOGLE_TOKEN_ENCRYPTION_KEY')
    secret = current_app.config.get('SECRET_KEY') or ''
    if explicit:
        try:
            return Fernet(explicit.encode('utf-8'))
        except (ValueError, TypeError):
            secret = explicit
    if not secret:
        raise CalendarIntegrationError('A Flask SECRET_KEY is required to encrypt Google tokens.')
    digest = hashlib.sha256(f'wandershots-google-calendar:{secret}'.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token_payload(payload):
    return _fernet().encrypt(payload.encode('utf-8')).decode('utf-8')


def decrypt_token_payload(payload):
    if not payload:
        raise ReconnectRequired('Google Calendar credentials are missing. Please reconnect.')
    try:
        return _fernet().decrypt(payload.encode('utf-8')).decode('utf-8')
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ReconnectRequired('Stored Google credentials can no longer be decrypted. Please reconnect.') from exc


def _oauth_client_config():
    client_id = current_app.config.get('GOOGLE_CLIENT_ID') or os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET') or os.environ.get('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise CalendarIntegrationError(
            'Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.'
        )
    return {
        'web': {
            'client_id': client_id,
            'client_secret': client_secret,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
            'redirect_uris': [],
        }
    }


def calendar_redirect_uri():
    configured = os.environ.get('GOOGLE_CALENDAR_REDIRECT_URI')
    if configured:
        return configured
    return url_for('views.google_calendar_callback', _external=True)


def _build_flow(state=None, code_verifier=None):
    flow = Flow.from_client_config(
        _oauth_client_config(),
        scopes=CALENDAR_SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = calendar_redirect_uri()
    return flow


def build_authorization_url():
    """Create a Google authorization URL and persist the OAuth state/PKCE data."""
    state = secrets.token_urlsafe(32)
    flow = _build_flow(state=state)
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=state,
    )
    session[OAUTH_STATE_SESSION_KEY] = state
    session[OAUTH_STARTED_SESSION_KEY] = int(time.time())
    session[OAUTH_VERIFIER_SESSION_KEY] = flow.code_verifier
    return authorization_url


def validate_oauth_state(state):
    expected = session.pop(OAUTH_STATE_SESSION_KEY, None)
    started = session.pop(OAUTH_STARTED_SESSION_KEY, 0)
    verifier = session.pop(OAUTH_VERIFIER_SESSION_KEY, None)
    if not expected or not state or not secrets.compare_digest(str(expected), str(state)):
        return False, None
    try:
        if time.time() - int(started or 0) > 900:
            return False, None
    except (TypeError, ValueError):
        return False, None
    return True, verifier


def _fetch_google_identity(credentials):
    try:
        response = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {credentials.token}'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return data.get('email'), data.get('name')
    except Exception as exc:  # pragma: no cover - external API
        logger.warning('Could not read Google account identity: %s', _safe_error(exc))
        return None, None


def complete_authorization(code, state):
    """Exchange an OAuth code, encrypt credentials and activate the connection."""
    valid, verifier = validate_oauth_state(state)
    if not valid:
        raise CalendarIntegrationError('The Google sign-in request expired or was invalid. Please try again.')
    flow = _build_flow(state=state, code_verifier=verifier)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    if not credentials or not credentials.refresh_token:
        raise CalendarIntegrationError(
            'Google did not return a refresh token. Remove WanderShots from your Google account permissions and try again.'
        )
    email, display_name = _fetch_google_identity(credentials)
    return save_connection(credentials, email=email, display_name=display_name)


def save_connection(credentials, email=None, display_name=None):
    connection = None
    if email:
        connection = (
            GoogleCalendarConnection.query
            .filter_by(email=email)
            .order_by(GoogleCalendarConnection.id.desc())
            .first()
        )
    if connection is None:
        connection = GoogleCalendarConnection()
        db.session.add(connection)

    connection.email = email
    connection.display_name = display_name
    connection.encrypted_credentials = encrypt_token_payload(credentials.to_json())
    connection.scopes = ' '.join(credentials.scopes or CALENDAR_SCOPES)
    connection.calendar_id = connection.calendar_id or 'primary'
    connection.is_active = True
    connection.needs_reconnect = False
    connection.last_error = None
    connection.disconnected_at = None
    connection.updated_at = utcnow()

    (
        GoogleCalendarConnection.query
        .filter(GoogleCalendarConnection.id != connection.id)
        .update(
            {
                GoogleCalendarConnection.is_active: False,
                GoogleCalendarConnection.updated_at: utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.session.commit()
    logger.info('Google Calendar connected for %s', email or 'an administrator account')
    return connection


def get_active_connection():
    return (
        GoogleCalendarConnection.query
        .filter_by(is_active=True)
        .order_by(GoogleCalendarConnection.connected_at.desc())
        .first()
    )


def load_credentials(connection):
    if not connection or not connection.is_active:
        raise ReconnectRequired('Google Calendar is not connected.')
    data = decrypt_token_payload(connection.encrypted_credentials)
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(data), CALENDAR_SCOPES)
    except (ValueError, KeyError, TypeError) as exc:
        raise ReconnectRequired('Stored Google credentials are invalid. Please reconnect.') from exc

    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(GoogleAuthRequest())
        except RefreshError as exc:
            raise ReconnectRequired(
                'Google authorization has expired or was revoked. Please reconnect Google Calendar.'
            ) from exc
        connection.encrypted_credentials = encrypt_token_payload(credentials.to_json())
        connection.updated_at = utcnow()
        db.session.commit()
    elif not credentials.valid and not credentials.refresh_token:
        raise ReconnectRequired('Google authorization is no longer valid. Please reconnect.')
    return credentials


def build_calendar_service(connection):
    credentials = load_credentials(connection)
    return build('calendar', 'v3', credentials=credentials, cache_discovery=False)


def disconnect_connection(connection, revoke=True):
    if not connection:
        return
    if revoke and connection.encrypted_credentials:
        try:
            credentials = load_credentials(connection)
            token = credentials.refresh_token or credentials.token
            if token:
                requests.post(
                    'https://oauth2.googleapis.com/revoke',
                    data={'token': token},
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    timeout=10,
                )
        except Exception as exc:  # pragma: no cover - external API
            logger.warning('Google token revocation failed: %s', _safe_error(exc))

    connection.is_active = False
    connection.needs_reconnect = False
    connection.encrypted_credentials = None
    connection.last_error = 'Disconnected by administrator.'
    connection.disconnected_at = utcnow()
    connection.updated_at = utcnow()
    (
        BookingCalendarSync.query
        .filter(
            BookingCalendarSync.connection_id == connection.id,
            BookingCalendarSync.sync_status != 'cancelled',
        )
        .update(
            {
                BookingCalendarSync.sync_status: 'disconnected',
                BookingCalendarSync.next_retry_at: None,
                BookingCalendarSync.updated_at: utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.session.commit()
    logger.info('Google Calendar disconnected for %s', connection.email or connection.id)


def resolve_duration_minutes(booking):
    text = f'{booking.package_selected or ""} {booking.notes or ""}'
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b', text, re.IGNORECASE)
    if match:
        try:
            return max(30, min(24 * 60, int(float(match.group(1)) * 60)))
        except (TypeError, ValueError):
            pass
    return SERVICE_DURATION_MINUTES.get(booking.service_type, 120)


def parse_booking_start(booking):
    date_text = (booking.date or '').strip()
    time_text = (booking.time or '').strip()
    if not date_text or not time_text:
        raise CalendarIntegrationError('Booking has no date or time.')
    parsed_time = None
    for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p'):
        try:
            parsed_time = datetime.strptime(time_text, fmt).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        raise CalendarIntegrationError('Booking time format is not recognized.')
    try:
        day = datetime.strptime(date_text, '%Y-%m-%d')
    except ValueError as exc:
        raise CalendarIntegrationError('Booking date format is not recognized.') from exc
    return day.replace(
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        second=0,
        microsecond=0,
        tzinfo=BOOKING_TIMEZONE,
    )


def booking_reference(booking):
    return f'WS-{int(booking.id):06d}'


def build_event_body(booking):
    start = parse_booking_start(booking)
    duration = resolve_duration_minutes(booking)
    end = start + timedelta(minutes=duration)
    reference = booking_reference(booking)
    service = booking.service_type or 'Session'
    customer = booking.customer_name or 'Customer'
    location = booking.location or 'WanderShots Studio'

    description_lines = [
        f'WanderShots booking reference: {reference}',
        f'Booking ID: {booking.id}',
        '',
        f'Customer: {customer}',
        f'Service: {service}',
        f'Package: {booking.package_selected or "Not specified"}',
        f'Date: {start.strftime("%A, %B %d, %Y")}',
        f'Time: {start.strftime("%I:%M %p")} - {end.strftime("%I:%M %p")} ({BOOKING_TIMEZONE_NAME})',
        f'Duration: {duration // 60}h {duration % 60:02d}m',
        f'Location: {location}',
        f'Contact email: {booking.customer_email or "Not provided"}',
        f'Contact phone: {booking.customer_phone or "Not provided"}',
    ]
    if booking.notes:
        description_lines.extend(['', 'Booking notes:', booking.notes])
    if booking.map_url:
        description_lines.append(f'Map: {booking.map_url}')

    return {
        'summary': f'WanderShots | {service} \u2013 {customer}',
        'description': '\n'.join(description_lines),
        'location': location,
        'start': {
            'dateTime': start.isoformat(),
            'timeZone': BOOKING_TIMEZONE_NAME,
        },
        'end': {
            'dateTime': end.isoformat(),
            'timeZone': BOOKING_TIMEZONE_NAME,
        },
        'status': 'confirmed',
        'visibility': 'private',
        'transparency': 'opaque',
        'reminders': {'useDefault': True},
        'extendedProperties': {
            'private': {
                'wandershots_booking_id': str(booking.id),
                'wandershots_reference': reference,
            }
        },
    }


def _deterministic_event_id(booking, connection, generation):
    digest = hashlib.sha256(
        f'wandershots:{booking.id}:{connection.id}:{int(generation or 0)}'.encode('utf-8')
    ).hexdigest()
    return digest


def _action_for_booking(booking, sync=None):
    if booking.status == 'scheduled':
        return 'upsert'
    if booking.status == 'cancelled':
        return 'delete'
    if booking.status == 'pending':
        return 'delete' if sync and sync.google_event_id else 'skip'
    if booking.status == 'finished':
        return 'skip'
    return 'skip'


def _get_or_create_sync_row(booking, connection):
    sync = (
        BookingCalendarSync.query
        .filter_by(booking_id=booking.id, connection_id=connection.id)
        .first()
    )
    if sync:
        return sync
    sync = BookingCalendarSync(
        booking_id=booking.id,
        connection_id=connection.id,
        desired_action='upsert',
        sync_status='pending',
        next_retry_at=utcnow(),
    )
    db.session.add(sync)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        sync = (
            BookingCalendarSync.query
            .filter_by(booking_id=booking.id, connection_id=connection.id)
            .first()
        )
    return sync


def _prepare_sync(booking, connection):
    sync = _get_or_create_sync_row(booking, connection)
    if not sync:
        return None
    action = _action_for_booking(booking, sync)
    if action == 'skip':
        if sync.google_event_id and sync.sync_status != 'synced':
            sync.sync_status = 'synced'
        elif not sync.google_event_id:
            sync.sync_status = 'skipped'
        sync.next_retry_at = None
        sync.last_error = None
        return sync
    sync.desired_action = action
    sync.sync_status = 'pending'
    sync.next_retry_at = utcnow()
    sync.last_error = None
    sync.retry_count = 0
    sync.updated_at = utcnow()
    return sync


def enqueue_booking_sync(booking, trigger=True):
    """Queue a booking for synchronization after the booking change is committed."""
    connection = get_active_connection()
    if not connection:
        return None
    sync = _prepare_sync(booking, connection)
    if sync is None:
        return None
    db.session.commit()
    if trigger:
        trigger_background_worker()
    return sync


def enqueue_all_confirmed_bookings(trigger=True):
    connection = get_active_connection()
    if not connection:
        return 0
    bookings = (
        Booking.query
        .filter_by(status='scheduled', is_archived=False)
        .order_by(Booking.id.asc())
        .all()
    )
    queued = 0
    for booking in bookings:
        sync = _prepare_sync(booking, connection)
        if sync is not None:
            queued += 1
    db.session.commit()
    if queued and trigger:
        trigger_background_worker()
    return queued


def retry_sync_row(sync_id):
    sync = db.session.get(BookingCalendarSync, int(sync_id))
    if not sync:
        return False
    connection = db.session.get(GoogleCalendarConnection, sync.connection_id)
    if not connection or not connection.is_active:
        return False
    sync.sync_status = 'pending'
    sync.next_retry_at = utcnow()
    sync.last_error = None
    sync.retry_count = 0
    sync.updated_at = utcnow()
    db.session.commit()
    trigger_background_worker()
    return True


def retry_booking_sync(booking_id):
    booking = db.session.get(Booking, int(booking_id))
    if not booking:
        return False
    connection = get_active_connection()
    if not connection:
        return False
    sync = _get_or_create_sync_row(booking, connection)
    if not sync:
        return False
    sync.sync_status = 'pending'
    sync.next_retry_at = utcnow()
    sync.last_error = None
    sync.retry_count = 0
    sync.desired_action = _action_for_booking(booking, sync)
    db.session.commit()
    trigger_background_worker()
    return True


def _claim_sync(sync, action):
    now = utcnow()
    result = db.session.execute(
        update(BookingCalendarSync)
        .where(BookingCalendarSync.id == sync.id)
        .where(
            or_(
                BookingCalendarSync.sync_status != 'processing',
                BookingCalendarSync.last_attempt_at.is_(None),
                BookingCalendarSync.last_attempt_at < now - timedelta(minutes=STALE_PROCESSING_MINUTES),
            )
        )
        .values(
            sync_status='processing',
            desired_action=action,
            last_attempt_at=now,
            next_retry_at=None,
            last_error=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return result.rowcount == 1


def _upsert_event(service, connection, sync, booking):
    body = build_event_body(booking)
    body['extendedProperties']['private']['wandershots_connection_id'] = str(connection.id)
    calendar_id = connection.calendar_id or 'primary'

    if sync.google_event_id:
        update_body = dict(body)
        update_body.pop('id', None)
        try:
            return service.events().update(
                calendarId=calendar_id,
                eventId=sync.google_event_id,
                body=update_body,
                sendUpdates='none',
            ).execute()
        except HttpError as exc:
            if _http_status(exc) not in (404, 410):
                raise
            # The event was removed directly in Google Calendar. Recreate it.
            sync.event_generation = int(sync.event_generation or 0) + 1
            sync.google_event_id = None

    event_id = _deterministic_event_id(booking, connection, sync.event_generation)
    insert_body = dict(body)
    insert_body['id'] = event_id
    try:
        return service.events().insert(
            calendarId=calendar_id,
            body=insert_body,
            sendUpdates='none',
        ).execute()
    except HttpError as exc:
        if _http_status(exc) != 409:
            raise
        # A previous attempt created the event but crashed before persisting
        # the mapping. Update the existing deterministic event instead.
        update_body = dict(body)
        update_body.pop('id', None)
        return service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=update_body,
            sendUpdates='none',
        ).execute()


def _delete_event(service, connection, sync):
    if not sync.google_event_id:
        return
    try:
        service.events().delete(
            calendarId=connection.calendar_id or 'primary',
            eventId=sync.google_event_id,
            sendUpdates='none',
        ).execute()
    except HttpError as exc:
        if _http_status(exc) not in (404, 410):
            raise
    sync.event_generation = int(sync.event_generation or 0) + 1
    sync.google_event_id = None
    sync.google_event_link = None


def sync_booking(booking_id):
    """Synchronize one booking if its queue row can be claimed atomically."""
    connection = get_active_connection()
    if not connection or connection.needs_reconnect:
        return False
    booking = db.session.get(Booking, int(booking_id))
    if not booking:
        return False
    sync = _get_or_create_sync_row(booking, connection)
    if not sync or sync.connection_id != connection.id:
        return False

    action = _action_for_booking(booking, sync)
    if action == 'skip':
        sync.sync_status = 'synced' if sync.google_event_id else 'skipped'
        sync.next_retry_at = None
        sync.updated_at = utcnow()
        db.session.commit()
        return True

    if not _claim_sync(sync, action):
        return False

    db.session.refresh(sync)
    try:
        service = build_calendar_service(connection)
        if action == 'delete':
            _delete_event(service, connection, sync)
            sync.sync_status = 'cancelled'
        else:
            event = _upsert_event(service, connection, sync, booking)
            sync.google_event_id = event.get('id') or sync.google_event_id
            sync.google_event_link = event.get('htmlLink') or sync.google_event_link
            sync.sync_status = 'synced'
        sync.last_synced_at = utcnow()
        sync.last_error = None
        sync.next_retry_at = None
        sync.retry_count = 0
        sync.updated_at = utcnow()
        connection.last_sync_at = utcnow()
        connection.last_error = None
        db.session.commit()
        logger.info('Google Calendar sync succeeded for booking %s (%s)', booking.id, action)
        return True
    except Exception as exc:
        db.session.rollback()
        _record_failure(sync.id, exc)
        return False


def _record_failure(sync_id, exc):
    sync = db.session.get(BookingCalendarSync, sync_id)
    if not sync:
        return
    connection = db.session.get(GoogleCalendarConnection, sync.connection_id)
    message = _safe_error(exc)
    retryable = _is_retryable(exc)

    status = _http_status(exc)
    # A 403 is only an auth problem when it is not a rate-limit/quota error.
    # Rate-limit 403s must stay retryable instead of disconnecting the account.
    reconnect_required = (
        isinstance(exc, (ReconnectRequired, RefreshError))
        or status == 401
        or (status == 403 and not retryable)
    )
    if reconnect_required:
        if connection:
            connection.needs_reconnect = True
            connection.is_active = False
            connection.last_error = message
        retryable = False

    sync.retry_count = int(sync.retry_count or 0) + 1
    sync.last_error = message
    sync.updated_at = utcnow()
    if retryable and sync.retry_count < MAX_RETRIES:
        delay = min(3600, 60 * (2 ** max(0, sync.retry_count - 1)))
        sync.sync_status = 'pending'
        sync.next_retry_at = utcnow() + timedelta(seconds=delay)
    else:
        sync.sync_status = 'failed'
        sync.next_retry_at = None
    if connection:
        connection.last_error = message
    db.session.commit()
    logger.warning('Google Calendar sync failed for booking %s: %s', sync.booking_id, message)


def _http_status(exc):
    status = getattr(exc, 'status_code', None)
    if status:
        return int(status)
    response = getattr(exc, 'resp', None)
    status = getattr(response, 'status', None)
    try:
        return int(status) if status else None
    except (TypeError, ValueError):
        return None


def _is_retryable(exc):
    if isinstance(exc, (ReconnectRequired, RefreshError)):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, TransportError, OSError)):
        return True
    status = _http_status(exc)
    if status in (408, 429, 500, 502, 503, 504):
        return True
    if status == 403:
        text = str(exc).lower()
        return any(marker in text for marker in ('ratelimitexceeded', 'userratelimitexceeded', 'quotaexceeded'))
    return False


def _safe_error(exc):
    message = str(exc) or exc.__class__.__name__
    message = re.sub(
        r'(?i)(access_token|refresh_token|client_secret|authorization|id_token)\s*[=:]\s*\S+',
        r'\1=[redacted]',
        message,
    )
    return message[:1000]


def trigger_background_worker(delay=0.0):
    """Run the durable queue in a short-lived thread (best-effort latency only)."""
    if current_app.config.get('DISABLE_CALENDAR_BACKGROUND_THREADS'):
        return
    app = current_app._get_current_object()

    def runner():
        if delay:
            time.sleep(delay)
        with app.app_context():
            try:
                process_due_sync_jobs()
            except Exception:
                logger.exception('Google Calendar background worker crashed')
            finally:
                db.session.remove()

    threading.Thread(target=runner, daemon=True, name='ws-calendar-sync').start()


def process_due_sync_jobs(limit=25):
    """Process due queue rows. Safe to run from multiple workers."""
    now = utcnow()
    stale = (
        BookingCalendarSync.query
        .filter(
            BookingCalendarSync.sync_status == 'processing',
            or_(
                BookingCalendarSync.last_attempt_at.is_(None),
                BookingCalendarSync.last_attempt_at < now - timedelta(minutes=STALE_PROCESSING_MINUTES),
            ),
        )
        .update(
            {
                BookingCalendarSync.sync_status: 'pending',
                BookingCalendarSync.next_retry_at: now,
                BookingCalendarSync.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    if stale:
        db.session.commit()

    rows = (
        BookingCalendarSync.query
        .join(
            GoogleCalendarConnection,
            BookingCalendarSync.connection_id == GoogleCalendarConnection.id,
        )
        .filter(
            GoogleCalendarConnection.is_active.is_(True),
            GoogleCalendarConnection.needs_reconnect.is_(False),
            BookingCalendarSync.sync_status == 'pending',
            or_(
                BookingCalendarSync.next_retry_at.is_(None),
                BookingCalendarSync.next_retry_at <= now,
            ),
        )
        .order_by(BookingCalendarSync.next_retry_at.asc(), BookingCalendarSync.id.asc())
        .limit(limit)
        .all()
    )
    processed = 0
    for row in rows:
        try:
            if sync_booking(row.booking_id):
                processed += 1
        except Exception:
            db.session.rollback()
            logger.exception('Unhandled Google Calendar queue error for sync row %s', row.id)
    return processed


def get_sync_map(booking_ids):
    if not booking_ids:
        return {}
    connection = get_active_connection()
    if not connection:
        return {}
    rows = (
        BookingCalendarSync.query
        .filter(
            BookingCalendarSync.connection_id == connection.id,
            BookingCalendarSync.booking_id.in_(list(booking_ids)),
        )
        .all()
    )
    return {row.booking_id: row for row in rows}


def get_sync_summary(connection=None):
    connection = connection or get_active_connection()
    if not connection:
        return {
            'connected': False,
            'counts': {},
            'failed': [],
            'total': 0,
        }
    counts = dict(
        db.session.query(BookingCalendarSync.sync_status, func.count(BookingCalendarSync.id))
        .filter(BookingCalendarSync.connection_id == connection.id)
        .group_by(BookingCalendarSync.sync_status)
        .all()
    )
    failed = (
        BookingCalendarSync.query
        .filter(
            BookingCalendarSync.connection_id == connection.id,
            BookingCalendarSync.sync_status == 'failed',
        )
        .order_by(BookingCalendarSync.last_attempt_at.desc())
        .limit(8)
        .all()
    )
    return {
        'connected': True,
        'counts': counts,
        'failed': failed,
        'total': sum(counts.values()),
    }


def get_connection_status():
    connection = get_active_connection()
    if not connection:
        return {
            'connected': False,
            'configured': bool(
                (current_app.config.get('GOOGLE_CLIENT_ID') or os.environ.get('GOOGLE_CLIENT_ID'))
                and (current_app.config.get('GOOGLE_CLIENT_SECRET') or os.environ.get('GOOGLE_CLIENT_SECRET'))
            ),
        }
    summary = get_sync_summary(connection)
    return {
        'connected': True,
        'configured': True,
        'email': connection.email,
        'display_name': connection.display_name,
        'needs_reconnect': bool(connection.needs_reconnect),
        'last_error': connection.last_error,
        'last_sync_at': _iso_utc(connection.last_sync_at),
        'connected_at': _iso_utc(connection.connected_at),
        'counts': summary['counts'],
        'failed_count': int(summary['counts'].get('failed', 0) or 0),
        'total': summary['total'],
    }
