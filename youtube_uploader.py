import os
import time
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

def get_authenticated_service():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        # Mock successful upload for local testing
        print("WARNING: YouTube credentials missing. Mocking upload...")
        return None

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    return build("youtube", "v3", credentials=credentials)

def upload_video(video_path, title, description, tags, thumbnail_path=None):
    youtube = get_authenticated_service()
    if not youtube:
        return "https://youtube.com/shorts/mock_id_for_testing"

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "24" # Entertainment
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    try:
        print(f"Uploading {video_path} to YouTube...")
        insert_request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
        )
        response = insert_request.execute()
        video_id = response.get("id")
        print(f"Upload successful! ID: {video_id}")
        
        if thumbnail_path and os.path.exists(thumbnail_path):
            print("Uploading thumbnail...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
        return f"https://www.youtube.com/shorts/{video_id}"
    except Exception as e:
        print(f"Upload failed: {e}")
        return None
