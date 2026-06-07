import sqlite3
import os

# Adjust this path if your dev.db is inside an 'instance' folder:
db_path = "instance/dev.db" 


if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Add the missing column to the table
        cursor.execute("ALTER TABLE charter_service ADD COLUMN total_processing_time VARCHAR(150) DEFAULT 'Varies'")
        conn.commit()
        conn.close()
        print("Success! The missing column was added to the database.")
    except sqlite3.OperationalError as e:
        print(f"Notice: {e} (The column might already exist)")
else:
    print(f"Error: Could not find {db_path}. If your DB is inside an 'instance' folder, update the db_path variable in this script.")