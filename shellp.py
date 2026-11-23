from website import create_app, db
from website.models import Booking

app = create_app()
with app.app_context():
    # Count bookings the graph expects
    booked = Booking.query.filter_by(status='scheduled', is_archived=False).count()
    cancelled = Booking.query.filter_by(status='cancelled', is_archived=False).count()
    print(f"Booked (scheduled, not archived): {booked}")
    print(f"Cancelled (cancelled, not archived): {cancelled}")

    if booked == 0 or cancelled == 0:
        # Seed test bookings so the graph has something to draw
        b1 = Booking(
            customer_name='Booked Customer',
            customer_email='booked@example.com',
            service_type='Studio Photoshoot',
            date='2025-12-01',
            time='10:00',
            status='scheduled',
            is_archived=False
        )
        b2 = Booking(
            customer_name='Cancelled Customer',
            customer_email='cancel@example.com',
            service_type='Studio Photoshoot',
            date='2025-12-02',
            time='14:00',
            status='cancelled',
            is_archived=False
        )
        db.session.add_all([b1, b2])
        db.session.commit()
        print("✅ Test bookings added.")