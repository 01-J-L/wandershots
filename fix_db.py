# --- fix_db.py ---
import sqlite3
import os

db_path = 'website/database.db'
if not os.path.exists(db_path):
    db_path = 'instance/database.db'

if not os.path.exists(db_path):
    print("❌ Could not find database.db.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ADD fb_post_id to portfolio_item table
    try:
        cursor.execute("ALTER TABLE portfolio_item ADD COLUMN fb_post_id VARCHAR(200)")
        print("✅ SUCCESS: Added 'fb_post_id' column to PortfolioItem table")
    except Exception as e:
        print(f"ℹ️ PortfolioItem table already has 'fb_post_id' or error: {e}")

    conn.commit()
    conn.close()
    print("\n🎉 Update complete!")