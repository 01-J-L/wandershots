import os
os.environ['DATABASE_URL']='sqlite:///smoke_test.db'
os.environ['DISABLE_SCHEDULER']='1'
os.environ['DISABLE_CALENDAR_BACKGROUND_THREADS']='1'
os.environ['SESSION_COOKIE_SECURE']='0'
os.environ['FLASK_SECRET_KEY']='test-secret-do-not-use-in-production'
os.environ['GROQ_API_KEY']='sk-test-key-not-real'
os.environ['GOOGLE_CLIENT_ID']='dummy-id'
os.environ['GOOGLE_CLIENT_SECRET']='dummy-secret'

from website import create_app, db
from website.models import Booking, User, GoogleCalendarConnection, BookingCalendarSync

app = create_app()
client = app.test_client()

# basic routes
for path in ['/', '/offline', '/sw.js']:
    r = client.get(path)
    print(f"{path}: {r.status_code} {r.headers.get('Content-Type')}", end='')
    if path == '/sw.js':
        print(f" ServiceWorkerAllowed={r.headers.get('Service-Worker-Allowed')}", end='')
    print()

# admin login
r = client.post('/admin_login', data={'username':'superadmin','password':'admin123'}, follow_redirects=False)
print(f"admin_login: {r.status_code} location={r.headers.get('Location')}")

r = client.get('/admin/calendar')
print(f"calendar-auth: {r.status_code} calendarConfig={'config' in r.get_data(as_text=True)}")

# Google calendar status JSON
r = client.get('/admin/google-calendar/status')
print(f"google-status: {r.status_code} is_json={r.is_json} data={r.get_json()}")

# API events
with app.app_context():
    # Create a simple booking
    b = Booking(
        customer_name='Smoke Test',
        customer_email='test@example.com',
        service_type='Studio Photoshoot',
        date='2026-12-01',
        time='10:00',
        status='scheduled',
        is_archived=False
    )
    db.session.add(b)
    db.session.commit()
    bid = b.id

r = client.get('/admin/api/calendar-events?start=2026-12-01&end=2026-12-02')
print(f"api-events: {r.status_code} is_json={r.is_json}")
if r.is_json:
    data = r.get_json()
    events = data.get('events', [])
    print(f"  events count: {len(events)}")
    if events:
        e = events[0]
        print(f"  first event sync_status={e.get('extendedProps',{}).get('sync_status')}")

# settings
r = client.get('/admin/settings')
settings_text = r.get_data(as_text=True)
print(f"settings: {r.status_code} 'Google' in settings_text}")

# offline banner
r = client.get('/offline')
print(f"offline: {r.status_code}")

print("\nSmoke test complete.")