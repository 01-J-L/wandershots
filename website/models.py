from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True) # Changed from email
    password = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    role = db.Column(db.String(50), default='admin')

class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    email = db.Column(db.String(150))
    message = db.Column(db.String(10000))
    date = db.Column(db.DateTime(timezone=True), default=func.now())
    is_archived = db.Column(db.Boolean, default=False)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(150))
    customer_email = db.Column(db.String(150))
    customer_phone = db.Column(db.String(50)) 
    reminder_sent = db.Column(db.Boolean, default=False)
    
    location = db.Column(db.String(200)) 
    map_url = db.Column(db.String(500))
    
    service_type = db.Column(db.String(50)) 
    package_selected = db.Column(db.String(150)) 
    
    date = db.Column(db.String(50))
    time = db.Column(db.String(50))
    notes = db.Column(db.String(1000))
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    status = db.Column(db.String(50), default='pending') 
    is_archived = db.Column(db.Boolean, default=False)


class PortfolioItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500))
    category = db.Column(db.String(50)) 
    link = db.Column(db.String(500)) 
    
    # Existing image fields...
    image_filename = db.Column(db.String(200), nullable=False) 
    image_filename_2 = db.Column(db.String(200))
    image_filename_3 = db.Column(db.String(200))
    image_filename_4 = db.Column(db.String(200))
    extra_count = db.Column(db.String(50)) 
    extra_media = db.Column(db.Text)
    
    # ADD THIS NEW LINE HERE:
    fb_post_id = db.Column(db.String(200)) 
    
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())

# NEW MODEL: ServicePackage
class ServicePackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(500))
    price = db.Column(db.String(50)) 
    package_type = db.Column(db.String(50)) 
    image_filename = db.Column(db.String(200)) # <--- NEW FIELD FOR PACKAGE IMAGE
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())


class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)

# NEW MODEL: SocialLink for dynamic social media icons and URLs
class SocialLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(100), nullable=False, unique=True) # e.g., "Facebook", "Instagram"
    url = db.Column(db.String(500), nullable=False)
    icon_class = db.Column(db.String(100)) # e.g., "ri-facebook-fill"
    order = db.Column(db.Integer, default=0) # For custom sorting

# NEW MODEL: QuickLink for dynamic footer navigation
class QuickLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) # e.g., "Wedding Photography"
    url = db.Column(db.String(500), nullable=False) # e.g., "/book", "/works"
    order = db.Column(db.Integer, default=0) # For custom sorting

class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100)) # e.g., Paper, Ink, Props, Equipment
    quantity = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=5) # Alert level
    unit = db.Column(db.String(50), default="pcs") # e.g., rolls, packs, pcs
    last_updated = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now())