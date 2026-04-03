import os
from typing import List, Optional
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from loguru import logger
from ..config import settings

class YouTubeService:
    def __init__(self,
                 client_id: str = settings.YOUTUBE_CLIENT_ID,
                 client_secret: str = settings.YOUTUBE_CLIENT_SECRET,
                 refresh_token: str = settings.YOUTUBE_REFRESH_TOKEN):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._youtube = None

    @property
    def youtube(self):
        if self._youtube is None:
            if not all([self.client_id, self.client_secret, self.refresh_token]):
                raise ValueError("YouTube API credentials are not fully set.")
            
            creds = Credentials(
                None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            self._youtube = build("youtube", "v3", credentials=creds)
        return self._youtube

    def upload_video(self,
                     file_path: str,
                     title: str,
                     description: str,
                     tags: List[str],
                     thumbnail_path: Optional[str] = None) -> Optional[str]:
        
        logger.info(f"Uploading Video: {title}")
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        
        try:
            request = self.youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()
            video_id = response.get("id")
            video_url = f"https://youtube.com/shorts/{video_id}"
            logger.info(f"✅ Upload successful: {video_url}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                self.upload_thumbnail(video_id, thumbnail_path)
            
            return video_url
        except Exception as e:
            logger.error(f"YouTube Upload Failed: {e}")
            return None

    def upload_thumbnail(self, video_id: str, thumbnail_path: str):
        logger.info(f"Uploading Thumbnail for {video_id}...")
        try:
            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            ).execute()
            logger.info("✅ Thumbnail Uploaded Successfully.")
        except Exception as e:
            logger.warning(f"Thumbnail Upload Failed: {e}")

youtube_service = YouTubeService()
