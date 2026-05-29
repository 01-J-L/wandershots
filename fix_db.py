import sqlite3
import os

# Check common database locations
db_path = 'instance/database.db'
if not os.path.exists(db_path):
    db_path = 'website/database.db'

print(f"Connecting to {db_path}...")
conn = sqlite3.connect(db_path)
c = conn.cursor()

try:
    # Adding the new gallery_link column
    c.execute("ALTER TABLE booking ADD COLUMN gallery_link VARCHAR(500)")
    print("✅ Added 'gallery_link' to Booking table successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Column already exists or error: {e}")

conn.commit()
conn.close()
print("🎉 Patch complete! You can now run your Flask app.")