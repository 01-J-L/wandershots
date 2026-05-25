# run_reminders.py
import os
import sys

# Add your project directory to the sys.path
project_home = u'/home/your_username/YOUR_REPO_NAME' # e.g., /home/your_username/wandershots-studio-app
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set up Flask app context
from website import create_app
app = create_app()
app.app_context().push() # Push the app context

from website.views import check_upcoming_events

print(f"[{os.environ.get('PA_TASK_NAME', 'Scheduled Task')}] Running scheduled event reminders...")
try:
    check_upcoming_events(app)
    print(f"[{os.environ.get('PA_TASK_NAME', 'Scheduled Task')}] Scheduled event reminders complete.")
except Exception as e:
    print(f"[{os.environ.get('PA_TASK_NAME', 'Scheduled Task')}] Error during reminders: {e}")

# Don't forget to exit the app context
app.app_context().pop()