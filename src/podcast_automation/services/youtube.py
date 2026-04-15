import os
import re
import isodate
import requests as http_requests
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
                 refresh_token: str = settings.YOUTUBE_REFRESH_TOKEN,
                 api_key: str = settings.YOUTUBE_API_KEY):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.api_key = api_key
        self._youtube_auth = None  # Authenticated client (for uploads)
        self._youtube_public = None  # Public API-key client (for reads)

    @property
    def youtube_auth(self):
        """Authenticated YouTube client — used for uploads only."""
        if self._youtube_auth is None:
            if not all([self.client_id, self.client_secret, self.refresh_token]):
                raise ValueError("YouTube OAuth credentials are not fully set. Cannot upload.")
            
            creds = Credentials(
                None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            self._youtube_auth = build("youtube", "v3", credentials=creds)
        return self._youtube_auth

    # Keep backward compat
    @property
    def youtube(self):
        return self.youtube_auth

    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Fetches official metadata for a video using the YouTube Data API.
        Uses API key (no OAuth needed) for this read-only public operation.
        Falls back to a direct HTTP request if no API key is set.
        """
        logger.info(f"Fetching metadata for: {video_id}")
        
        # Strategy 1: Use YouTube Data API with API key (most reliable)
        if self.api_key:
            return self._fetch_metadata_api_key(video_id)
        
        # Strategy 2: Use OAuth client (if available, but may fail if token expired)
        if all([self.client_id, self.client_secret, self.refresh_token]):
            result = self._fetch_metadata_oauth(video_id)
            if result:
                return result
        
        # Strategy 3: Use oembed endpoint (no auth needed, but no duration)
        return self._fetch_metadata_oembed(video_id)

    def _fetch_metadata_api_key(self, video_id: str) -> Optional[Dict]:
        """Fetch metadata using YouTube Data API v3 with an API key (no OAuth)."""
        try:
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "snippet,contentDetails",
                "id": video_id,
                "key": self.api_key,
            }
            response = http_requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("items"):
                logger.warning(f"No video found for ID: {video_id}")
                return None
                
            item = data["items"][0]
            snippet = item["snippet"]
            content_details = item["contentDetails"]
            
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
            logger.error(f"API Key metadata fetch failed: {e}")
            return None

    def _fetch_metadata_oauth(self, video_id: str) -> Optional[Dict]:
        """Fetch metadata using OAuth-authenticated client."""
        try:
            request = self.youtube_auth.videos().list(
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
            logger.error(f"OAuth metadata fetch failed: {e}")
            return None

    def _fetch_metadata_oembed(self, video_id: str) -> Optional[Dict]:
        """
        Fallback: Use YouTube oEmbed endpoint.
        This gives title but NOT duration, so we return duration=0 
        and let the caller decide.
        """
        try:
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = http_requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return {
                "id": video_id,
                "title": data.get("title", "Unknown"),
                "description": "",
                "duration": 0,  # oEmbed doesn't provide duration
                "thumbnail": data.get("thumbnail_url"),
            }
        except Exception as e:
            logger.error(f"oEmbed metadata fetch failed: {e}")
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
            request = self.youtube_auth.videos().insert(part="snippet,status", body=body, media_body=media)
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
            self.youtube_auth.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            ).execute()
            logger.info("✅ Thumbnail Uploaded Successfully.")
        except Exception as e:
            logger.warning(f"Thumbnail Upload Failed: {e}")

    def get_channel_latest_videos(self, channel_id: str, max_results: int = 5) -> List[Dict]:
        """
        Fetches the latest videos from a channel using the official Data API.
        Highly reliable and bypasses all scraping blocks.
        """
        logger.info(f"Fetching latest videos for channel: {channel_id}")
        try:
            # 1. Get the uploads playlist ID (UC... -> UU...)
            uploads_playlist_id = "UU" + channel_id[2:]
            
            # 2. List playlist items
            url = "https://www.googleapis.com/youtube/v3/playlistItems"
            params = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": max_results,
                "key": self.api_key,
            }
            response = http_requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            videos = []
            for item in data.get("items", []):
                snippet = item["snippet"]
                content_details = item["contentDetails"]
                video_id = content_details["videoId"]
                videos.append({
                    "id": video_id,
                    "title": snippet["title"],
                    "url": f"https://www.youtube.com/watch?v={video_id}"
                })
            
            return videos
        except Exception as e:
            logger.error(f"Official Channel Fetch Failed: {e}")
            return []

youtube_service = YouTubeService()
