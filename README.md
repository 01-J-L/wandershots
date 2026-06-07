# Flask + PostgreSQL Starter (VS Code Ready)

This is a tiny Flask app using SQLAlchemy and Flask-Login, set up for PostgreSQL (with a SQLite fallback for quick testing).

## Quick Start

1) **Open in VS Code**
- Extract this folder and open it in VS Code.

2) **Create a virtual environment**
```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

3) **Install dependencies**
```bash
pip install -r requirements.txt
```

4) **Configure the database**
- Copy `.env.example` to `.env` and edit the `DATABASE_URL` for your PostgreSQL instance, e.g.:
```
DATABASE_URL=postgresql+psycopg://flask_user:your_password@localhost:5432/flask_demo
SECRET_KEY=change_me_please
FLASK_DEBUG=1
```
> If `DATABASE_URL` is missing, the app will **fallback to SQLite** (`dev.db`) so you can still run quickly.

5) **Run**
```bash
# Option A
python main.py

# Option B
# Use the VS Code Run/Debug (F5) with "Flask App" configuration
```
Visit http://127.0.0.1:5000

## What it does
- Sign up / Log in / Log out (passwords hashed with PBKDF2-SHA256).
- Add simple text notes tied to the logged-in user (stored in the DB).

## Structure
```
flask_pg_demo/
├─ .env.example
├─ README.md
├─ requirements.txt
├─ main.py
└─ webapp/
   ├─ __init__.py
   ├─ models.py
   ├─ views.py
   ├─ auth.py
   ├─ templates/
   │  ├─ base.html
   │  ├─ home.html
   │  ├─ login.html
   │  ├─ signup.html
   │  └─ notes.html
   └─ static/
      └─ styles.css
```

## Notes
- For production, switch to proper migrations (Flask-Migrate) instead of `db.create_all()` convenience.
- The included `requirements.txt` pins commonly compatible versions.
