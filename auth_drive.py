import os
from google_auth_oauthlib.flow import InstalledAppFlow

# This tells Google we want permission to upload files
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def authenticate():
    print("Opening browser to authenticate your Google Account...")
    
    # This reads the credentials.json you downloaded
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    
    # This opens a browser window asking you to log in
    creds = flow.run_local_server(port=0)
    
    # This saves the login token so Flask can use it later!
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
        
    print("✅ Success! 'token.json' has been created. You can now use the gallery uploader!")

if __name__ == '__main__':
    authenticate()