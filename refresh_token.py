"""
YouTube OAuth2 Refresh Token Generator
========================================
Run this locally to generate a new YOUTUBE_REFRESH_TOKEN.

Prerequisites:
  pip install google-auth-oauthlib

Steps:
  1. Go to https://console.cloud.google.com/apis/credentials
  2. Find your OAuth 2.0 Client (Desktop type)
  3. Download the client_secret JSON file and save it as 'client_secret.json' 
     in this directory, OR set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET 
     environment variables / .env file.
  4. Run: python refresh_token.py
  5. A browser window will open — sign in with your YouTube channel's Google account.
  6. Copy the printed REFRESH TOKEN and update your GitHub Secret:
       gh secret set YOUTUBE_REFRESH_TOKEN --body "YOUR_NEW_TOKEN"
"""

import os
import json
import sys

# Try loading from .env first
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

def get_credentials_from_env():
    """Try to build client config from environment variables."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    
    if client_id and client_secret:
        return {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    return None


def get_credentials_from_file():
    """Try to load client config from client_secret.json."""
    secret_file = os.path.join(os.path.dirname(__file__), "client_secret.json")
    if os.path.exists(secret_file):
        with open(secret_file, "r") as f:
            return json.load(f)
    return None


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib is not installed.")
        print("Run: pip install google-auth-oauthlib")
        sys.exit(1)
    
    # Try environment variables first, then client_secret.json
    client_config = get_credentials_from_env()
    source = "environment variables"
    
    if not client_config:
        client_config = get_credentials_from_file()
        source = "client_secret.json"
    
    if not client_config:
        print("=" * 60)
        print("ERROR: No OAuth2 credentials found!")
        print()
        print("Option A: Set environment variables (or in .env):")
        print("  YOUTUBE_CLIENT_ID=your_client_id")
        print("  YOUTUBE_CLIENT_SECRET=your_client_secret")
        print()
        print("Option B: Download client_secret.json from:")
        print("  https://console.cloud.google.com/apis/credentials")
        print("  and save it in this directory.")
        print("=" * 60)
        sys.exit(1)
    
    print(f"Using credentials from: {source}")
    print("Opening browser for OAuth consent...")
    print()
    
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    credentials = flow.run_local_server(port=8080, prompt="consent")
    
    print()
    print("=" * 60)
    print("✅ SUCCESS! Here are your new credentials:")
    print("=" * 60)
    print()
    print(f"REFRESH TOKEN:\n{credentials.refresh_token}")
    print()
    print("=" * 60)
    print()
    print("Now update your GitHub Secret with this command:")
    print()
    print(f'  gh secret set YOUTUBE_REFRESH_TOKEN --body "{credentials.refresh_token}"')
    print()
    print("Or go to: https://github.com/rajshevde-01/Podcast-Automation/settings/secrets/actions")
    print("and manually update YOUTUBE_REFRESH_TOKEN.")
    print("=" * 60)


if __name__ == "__main__":
    main()
