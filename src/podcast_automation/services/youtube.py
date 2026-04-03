import os
import re
import isodate
from typing import List, Optional, Dict
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

    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Fetches official metadata for a video using the YouTube Data API.
        This is much more reliable than scraping in automated environments.
        """
        logger.info(f"Fetching Official API Metadata for: {video_id}")
        try:
            request = self.youtube.videos().list(
                part="snippet,contentDetails",
                id=video_id
            )
            response = request.execute()
            
            if not response.get("items"):
                logger.warning(f"No video found for ID: {video_id}")
                return None
                
            item = response["items"][0]
            snippet = item["snippet"]
            content_details = item["contentDetails"]
            
            # Parse ISO 8601 duration (e.g., PT1H2M3S) to seconds
            duration_iso = content_details.get("duration")
            duration_seconds = int(isodate.parse_duration(duration_iso).total_seconds())
            
            return {
                "id": video_id,
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "duration": duration_seconds,
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url")
            }
        except Exception as e:
            logger.error(f"YouTube Data API Metadata Fetch Failed: {e}")
            return None

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
